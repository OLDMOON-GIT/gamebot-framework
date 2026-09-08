"""리니지 클래식 사냥 관리자 — 공식 ATS 엔진 구동 사이클 (설계 v2).

사용자 설계 v2(2026-09-08): 전투·물약·버프·위험 귀환은 전부 공식 ATS에
위임한다(Alt+W 설정, Alt+G 시작). 봇은 ATS 밖의 시나리오, 즉 사냥 관리자
역할만 운전한다.

TOWN → SUPPLY → SELECT_HUNT → MOVE → ATS_HUNT → RETURN → TOWN …
ATS_HUNT에서 긴급귀환 → RETURN, ATS 잔여 0 → END.

안전장치 3계층:
L0 공식 ATS 내장 : HP 긴급귀환(40%) / 무게 귀환(80%) / 비전투 귀환
L1 관리자 예방   : 주홍 안전재고(기본 50개) 이하 → 정상 귀환
L2 관리자 비상   : 화면 판독 불가 → 입력 전면 정지 후 대기

장비 구매·개인상점·캐시 결제·본인인증은 자동화 대상이 아니다(사람 몫).
좌표는 CDP 창(1933x1332) 실측값을 hunt_config.json에 두고 교체한다.
"""

import argparse
import datetime as dt
import json
import logging
import time
from pathlib import Path

import cv2

from linux_vision import analyze

CONFIG_PATH = Path(__file__).parent / "hunt_config.json"
LOG_PATH = Path(__file__).parent / "hunt_log.jsonl"
RUNTIME = Path("/tmp/linc-cycle")
STOP_PATH = RUNTIME / "stop"

STATES = ("TOWN", "SUPPLY", "SELECT_HUNT", "MOVE", "ATS_HUNT", "RETURN", "END")

# 귀환 원인 태그(설계 11번 — 귀환 후 판단이 핵심)
RETURN_REASONS = ("potion_preempt", "hp_danger", "weight", "idle_no_combat",
                  "ats_time_over", "manager_stop", "unknown")


class CycleBot:
    def __init__(self, window, config):
        self.window = window
        self.cfg = config
        self.state = "TOWN"
        self.ground_idx = 0
        self.today = dt.date.today().isoformat()
        self.excluded = {}          # {날짜: {사냥터명: 제외사유}} — 당일 제외
        self.emergency_returns = {} # {사냥터명: 긴급귀환 연속 횟수}
        self.hunt_started = 0.0
        self.hp_low_since = None
        self.return_reason = None   # RETURN 원인 태그
        self.current_ground = None
        self.stats = {"potions": 0, "emergency": 0}
        self._prev_frame = None
        self._ats_configured = False
        self._ats_started = False
        self._stall_count = 0

    # --- 공통 ---
    def read(self):
        """안전 판독: 활성 게임 화면에서만 상태를 읽는다. 실패 시 None."""
        if not self.window.active():
            return None
        try:
            frame = self.window.capture()
        except (RuntimeError, OSError):
            return None
        state = analyze(frame, target_profiles={}, require_url=False)
        state["_frame"] = frame
        return state

    def click(self, x, y, hover=0.0):
        geo = self.window.geometry()
        self.window.click(x, y, geo, hover=hover)

    def grounds(self):
        """당일 제외를 제외한 현재 사냥터 목록(우선순위순)."""
        banned = self.excluded.get(self.today, set())
        return [g for g in self.cfg.get("hunting_grounds", [])
                if g.get("name") not in banned]

    def ground_name(self):
        return self.current_ground or "?"

    # --- 상태 동작 ---
    def run_town(self, view):
        """마을 대기: 위치 확인 + ATS 잔여 확인(0이면 END)."""
        if view is None or view["hp"] is None:
            return "TOWN", "판독 불가 대기(모르는 화면=정지)"
        if view["hp"] == 0:
            self.return_reason = "hp_danger"
            return "RETURN", "사망 상태: 귀환 처리로"
        if not view["safe_zone"]:
            # 필드에 서 있으면 일단 귀환(ATS가 이미 보낸 경우도 이 경로)
            return "RETURN", "필드에 있음: 귀환 원인 판별로"
        ats_left = self.ats_time_left(view)
        if ats_left is not None and ats_left <= 0:
            charged = self.try_charge_ats()
            if not charged:
                return "END", "ATS 잔여 0: 오늘은 종료(06시 갱신)"
        return "SUPPLY", f"마을 확인 ATS잔여={ats_left}"

    def ats_time_left(self, view):
        """ATS 잔여 시간 판독(분). 좌표 미실측이면 None(판단 보류)."""
        reader = self.cfg.get("ats_time_reader")
        if not reader:
            return None
        frame = view.get("_frame") if view else None
        if frame is None:
            return None
        from linux_vision import crop, ocr
        text = ocr(crop(frame, tuple(reader)), whitelist="0123456789:")
        try:
            hh, mm = text.split(":")
            return int(hh) * 60 + int(mm)
        except ValueError:
            return None

    def try_charge_ats(self):
        """톱니바퀴 충전(설정 좌표가 있을 때만 시도). 성공 여부 반환."""
        charge = self.cfg.get("ats_charge_clicks")
        if not charge:
            return False
        for x, y in charge:
            self.click(x, y)
            time.sleep(0.8)
        return True

    def run_supply(self, view):
        """보급: 소모품 목표 수량 확보 전에는 출발 금지."""
        from ground_ranker import load_records, order_config_grounds
        ordered = order_config_grounds(self.cfg, load_records())
        names_before = [g.get("name") for g in self.cfg.get("hunting_grounds", [])]
        if [g.get("name") for g in ordered] != names_before:
            logging.info("사냥터 우선순위 재조정: %s", [g["name"] for g in ordered])
            self.cfg["hunting_grounds"] = ordered
            self.ground_idx = 0
        inv = self.cfg.get("inventory_button")
        if not inv:
            return "SUPPLY", "인벤 좌표 미실측: 사람 보급 대기(터치 없음)"
        self.click(*inv)
        time.sleep(1.0)
        after = self.read()
        if after is None:
            return "SUPPLY", "인벤 판독 실패: 재시도"
        # TODO(실측 후): 인벤 그리드에서 주홍/용기/2단/귀환주문서 수량 OCR.
        # 귀환 주문서 0개면 절대 출발 금지(설계 원칙) — 실측 전엔 사람 판단.
        return "SELECT_HUNT", "보급 확인(수량 판독은 인벤 실측 후 연결)"

    def run_select_hunt(self, view):
        """사냥터 선택: 당일 제외 필터 + 우선순위 순서."""
        pool = self.grounds()
        if not pool:
            return "END", "당일 이용 가능 사냥터 없음"
        ground = pool[self.ground_idx % len(pool)]
        self.current_ground = ground["name"]
        return "MOVE", f"사냥터 결정: {ground['name']}"

    def run_move(self, view):
        """이동: 두루마리 즐겨찾기/입장 NPC → 도착 확인."""
        pool = self.grounds()
        ground = pool[self.ground_idx % len(pool)]
        steps = [self.cfg["scroll_button"]] + ground.get("scroll_path", [])
        for x, y in steps:
            self.click(x, y)
            time.sleep(0.9)
        time.sleep(4.0)
        arrived = self.read()
        if arrived is None or arrived["hp"] is None:
            return "MOVE", "이동 후 판독 불가: 재시도"
        if arrived["safe_zone"]:
            return "MOVE", "아직 마을: 이동 재시도"
        self.hunt_started = time.monotonic()
        self.hp_low_since = None
        self.stats = {"potions": 0, "emergency": 0}
        return "ATS_HUNT", f"도착: {ground['name']}"

    def ats_on(self):
        """ATS 시작 — 실측 검증 클릭 경로(행동창→자동사냥→시작)를 우선하고
        Alt+G는 보조로만 시도한다(웹플레이 키 소비 여부 미실측)."""
        try:
            self.window.hotkey("Alt+G")
        except (AttributeError, RuntimeError, ValueError):
            pass
        for x, y in self.cfg["ats_clicks"]:
            self.click(x, y)
            time.sleep(0.8)

    def ats_setup(self):
        """Alt+W 설정(회복 70%/긴급 40%/무게 80%/탐색 18걸음) — 최초 1회."""
        try:
            self.window.hotkey("Alt+W")
            time.sleep(0.8)
            for x, y in self.cfg.get("ats_setup_clicks", []):
                self.click(x, y)
                time.sleep(0.6)
            return True
        except (AttributeError, RuntimeError, ValueError):
            return False

    def run_ats_hunt(self, view):
        """ATS에 사냥을 맡기고 감시만 한다(전투 개입 없음)."""
        if view is None or view["hp"] is None:
            return "ATS_HUNT", "판독 불가 대기"
        hp = view["hp"]
        cfg = self.cfg
        # L0가 먼저 떨어져 마을에 있으면(ATS 자체 귀환) 원인 추론으로 RETURN.
        if view["safe_zone"]:
            self.return_reason = self.infer_return_reason(view)
            return "RETURN", f"ATS 자체 귀환 감지(추정 원인={self.return_reason})"
        if hp == 0:
            self.return_reason = "hp_danger"
            return "RETURN", "사망"
        # ATS 시작은 최초 1회 + 비정상 정지 감지 시에만(매 스텝 반복 금지).
        if not self._ats_started:
            if not self._ats_configured:
                self._ats_configured = self.ats_setup()
            self.ats_on()
            self._ats_started = True
        elif self.screen_stalled(view.get("_frame")):
            logging.info("화면 비정상 정지: ATS 재시작")
            self.ats_on()
            self._stall_count = 0  # 재시작 직후 다시 정지 판정 초기화
        # L1 예방: 주홍 안전재고 이하 → 정상 귀환(공식 ATS는 개수 기준 미지원).
        potions = self.quickslot_potions(view)
        if potions is not None and potions <= cfg.get("potion_reserve", 50):
            self.return_reason = "potion_preempt"
            return "RETURN", f"주홍 안전재고({potions}개): 예방 귀환"
        # 감시 지표: HP 추이(긴급귀환 직전 상황 기록용).
        now = time.monotonic()
        danger = cfg.get("danger_hp", 0.40)
        if hp < danger:
            if self.hp_low_since is None:
                self.hp_low_since = now
        else:
            self.hp_low_since = None
        # 사냥 시간 종료 → 다음 사냥터(ATS 잔여가 남아 있을 때).
        if now - self.hunt_started > cfg.get("hunt_minutes", 150) * 60:
            self.ground_idx += 1
            self.return_reason = "ats_time_over"
            return "RETURN", "사냥 시간 종료: 다음 사냥터"
        return "ATS_HUNT", f"감시 HP={hp:.2f} 주홍={potions}"

    def quickslot_potions(self, view):
        """퀵슬롯 주홍 개수 판독. 좌표 미실측/실패면 None(예방 귀환 비활성)."""
        rect = self.cfg.get("quickslot_potion_count_rect")
        frame = view.get("_frame") if view else None
        if not rect or frame is None:
            return None
        from linux_vision import crop, ocr
        text = ocr(crop(frame, tuple(rect)), whitelist="0123456789")
        return int(text) if text.isdigit() else None

    def infer_return_reason(self, arrival_view):
        """ATS 자체 귀환의 원인을 마을 도착 화면에서 추론한다(설계 11번)."""
        hp = arrival_view.get("hp")
        if hp is not None and hp < 0.50:
            return "hp_danger"
        if hp is not None and hp >= 0.90:
            potions = self.quickslot_potions(arrival_view)
            if potions is not None and potions <= self.cfg.get("potion_reserve", 50):
                return "potion_preempt"
            return "idle_no_combat"
        return "unknown"

    def run_return(self, view):
        """귀환 처리: 원인별 대응 + 긴급귀환 연속 시 당일 제외."""
        reason = self.return_reason or "unknown"
        name = self.ground_name()
        if reason in ("hp_danger",):
            self.stats["emergency"] += 1
            self.emergency_returns[name] = self.emergency_returns.get(name, 0) + 1
            if self.emergency_returns.get(name, 0) >= 2:
                self.excluded.setdefault(self.today, {})[name] = "긴급귀환 2회"
                self.emergency_returns[name] = 0
                self.ground_idx += 1
                logging.info("사냥터 당일 제외: %s", name)
        elif reason in ("ats_time_over", "unknown", "manager_stop"):
            self.emergency_returns.pop(name, None)
        self.log_cycle(reason)
        self.return_reason = None
        return "TOWN", f"귀환 완료 원인={reason}"

    def screen_stalled(self, frame, need=3):
        """연속 정지 프레임으로 ATS 멈춤을 판정한다(한 번으로 오판 금지)."""
        if frame is None:
            return False
        if self._prev_frame is None or self._prev_frame.shape != frame.shape:
            self._prev_frame = frame
            self._stall_count = 0
            return False
        diff = cv2.absdiff(frame, self._prev_frame).max()
        self._prev_frame = frame
        if diff < 4:
            self._stall_count += 1
        else:
            self._stall_count = 0
        return self._stall_count >= need

    def log_cycle(self, reason="unknown"):
        record = {"t": time.time(), "date": self.today, "ground": self.ground_name(),
                  "minutes": round((time.monotonic() - self.hunt_started) / 60, 1),
                  "potions": self.stats.get("potions", 0),
                  "emergency": self.stats.get("emergency", 0),
                  "reason": reason}
        with LOG_PATH.open("a", encoding="utf-8") as sink:
            sink.write(json.dumps(record, ensure_ascii=False) + "\n")

    HANDLERS = {}

    def step(self):
        view = self.read()
        handler = getattr(self, "run_" + self.state.lower())
        new_state, message = handler(view)
        if new_state != self.state:
            logging.info("상태 전이 %s → %s (%s)", self.state, new_state, message)
        self.state = new_state
        return message


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdp", action="store_true", help="CDP 크롬 백엔드")
    parser.add_argument("--seconds", type=float, default=3600)
    parser.add_argument("--interval", type=float, default=3.0)
    args = parser.parse_args()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    STOP_PATH.unlink(missing_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if args.cdp:
        from cdp_window import CdpWindow
        window = CdpWindow()
    else:
        from linux_window import PurpleWindow
        window = PurpleWindow()
    bot = CycleBot(window, config)
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            if STOP_PATH.exists():
                logging.info("중지 요청")
                bot.return_reason = "manager_stop"
                break
            message = bot.step()
            logging.info("[%s] %s", bot.state, message)
            time.sleep(args.interval)
    finally:
        window.close()


if __name__ == "__main__":
    main()
