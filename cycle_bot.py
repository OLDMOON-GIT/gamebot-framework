"""리니지 클래식 사이클 봇 — 마을→보급→버프→이동→ATS 감시→귀환 루프.

사용자 설계(2026-09-08) 구현. 사냥 자체는 게임 내장 ATS에 위임하고,
봇은 한 사이클("출발 → 버프 → 사냥 → 위험판단 → 귀환 → 보충 → 다음
사냥터 → 재출발")의 운전만 담당한다. 장비 구매·개인거래·본인인증은
사람 몫이고 봇은 건드리지 않는다.

판독 불가 화면에서는 절대 입력하지 않는다(모르는 화면 = 정지).
좌표는 CDP 창(1933x1332) 실측값을 hunt_config.json에 두고 교체한다.
"""

import argparse
import json
import logging
import os
import time
from pathlib import Path

import cv2

from linux_vision import (analyze, find_character, forbidden_mob_check,
                          mob_hp_bars, zone_kind, zone_read)

CONFIG_PATH = Path(__file__).parent / "hunt_config.json"
LOG_PATH = Path(__file__).parent / "hunt_log.jsonl"
RUNTIME = Path("/tmp/linc-cycle")
STOP_PATH = RUNTIME / "stop"

# 상태 정의(사용자 설계의 최종 루프 그대로)
STATES = ("BOOT", "SUPPLY", "BUFF", "TRAVEL", "HUNT", "RETREAT", "RECOVER")


class CycleBot:
    def __init__(self, window, config):
        self.window = window
        self.cfg = config
        self.state = "BOOT"
        self.ground_idx = 0          # 사냥터 우선순위 커서
        self.deaths_at_ground = {}   # 사냥터별 연속 사망(2회 = 강등)
        self.hunt_started = 0.0
        self.potion_clicks = 0
        self.hp_low_since = None     # HP<50% 지속 시작 시각
        self.last_potion_effective = True
        self.stats = {"kills_signal": 0, "potions": 0, "exp_sample": []}

    # --- 공통 판독 ---
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

    # --- 상태별 동작 ---
    def run_boot(self, view):
        """현재 위치 판정: 마을/필드/사망/판독불가."""
        if view is None or view["hp"] is None:
            return "BOOT", "판독 불가 대기(모르는 화면=정지)"
        if view["hp"] == 0:
            return "RECOVER", "사망 상태 감지"
        if view["safe_zone"]:
            return "SUPPLY", "마을 확인"
        return "RETREAT", "필드에 있음: 일단 귀환부터"

    def run_supply(self, view):
        """소모품 확인. 부족하면 상점 구매(좌표는 config). 사람이 채워주면 통과."""
        # 마을 복귀 시점에 사냥 기록으로 사냥터 우선순위를 재계산한다(설계 13번).
        from ground_ranker import load_records, order_config_grounds
        grounds = order_config_grounds(self.cfg, load_records())
        if [g.get("name") for g in grounds] != [g.get("name") for g in self.cfg.get("hunting_grounds", [])]:
            logging.info("사냥터 우선순위 재조정: %s", [g["name"] for g in grounds])
            self.cfg["hunting_grounds"] = grounds
            self.ground_idx = 0
        need = self.cfg.get("min_potions", 50)
        # 인벤을 열어 물약 수량을 확인한다 — 좌표 미실측이면 보류 판정.
        inv = self.cfg.get("inventory_button")
        if not inv:
            return "SUPPLY", "인벤 좌표 미실측: 사람 보급 대기(터치 없음)"
        self.click(*inv)
        time.sleep(1.0)
        after = self.read()
        if after is None:
            return "SUPPLY", "인벤 판독 실패: 재시도"
        # TODO(실측 후): 인벤 그리드에서 주홍/용기/귀환주문서 수량 OCR.
        return "BUFF", "보급 확인(수량 판돁은 인벤 실측 후 연결)"

    def run_buff(self, view):
        """출발 전 버프: 용기 → 2단 가속 → (전투강화)."""
        for buff in self.cfg.get("buff_clicks", []):
            self.click(*buff)
            time.sleep(0.8)
        return "TRAVEL", "버프 적용"

    def run_travel(self, view):
        """말하는 두루마리 즐겨찾기로 사냥터 이동."""
        grounds = self.cfg.get("hunting_grounds", [])
        if not grounds:
            return "SUPPLY", "사냥터 목록 없음"
        ground = grounds[self.ground_idx % len(grounds)]
        steps = [self.cfg["scroll_button"]] + ground.get("scroll_path", [])
        for x, y in steps:
            self.click(x, y)
            time.sleep(0.9)
        time.sleep(4.0)  # 이동 로딩
        arrived = self.read()
        if arrived is None or arrived["hp"] is None:
            return "TRAVEL", "이동 후 판독 불가: 재시도"
        if arrived["safe_zone"]:
            return "TRAVEL", "아직 마을: 이동 재시도"
        self.hunt_started = time.monotonic()
        self.hp_low_since = None
        self.potion_clicks = 0
        return "HUNT", f"도착: {ground['name']}"

    def ats_start(self):
        for x, y in self.cfg["ats_clicks"]:
            self.click(x, y)
            time.sleep(0.8)

    def run_hunt(self, view):
        """ATS 구동 + 감시: HP/물약/위험/ATS정지/사망."""
        if view is None or view["hp"] is None:
            return "HUNT", "판독 불가 대기"
        hp = view["hp"]
        cfg = self.cfg
        potion_hp = cfg.get("potion_hp", 0.65)
        # 1) 사망
        if hp == 0:
            return "RECOVER", "전투 중 사망"
        # 2) 저체력: 물약은 기본 ATS에 맡긴다(실측 2026-09-08: 게임 ATS가
        # HP 70% 부근에서 스스로 마셔 유지한다). ATS 위임이 아니어야만
        # 봇이 퀵슬롯을 직접 누른다.
        if hp < potion_hp and not cfg.get("ats_potion", True):
            self.click(*cfg["quickslot_potion"])
            self.stats["potions"] += 1
            time.sleep(1.5)
            # 물약 무효 판정: 먹었는데 계속 하락/미회복
            check = self.read()
            if check and check["hp"] is not None and check["hp"] < hp + 0.02:
                self.last_potion_effective = False
            else:
                self.last_potion_effective = True
        elif hp < potion_hp:
            # ATS 위임 모드: 저체력인데 회복이 없으면 물약 소진 신호로 쓴다.
            check = self.read()
            if check and check["hp"] is not None and check["hp"] < hp + 0.02:
                self.last_potion_effective = False
            else:
                self.last_potion_effective = True
        # 3) 위험 이탈: HP<50% 지속 + 물약 무효 → 귀환
        now = time.monotonic()
        if hp < cfg.get("danger_hp", 0.50):
            if self.hp_low_since is None:
                self.hp_low_since = now
            elif now - self.hp_low_since > cfg.get("danger_seconds", 8):
                if not self.last_potion_effective:
                    return "RETREAT", "물약 무효 + 저체력 지속: 생존 우선 귀환"
        else:
            self.hp_low_since = None
        # 4) 사냥 시간 종료 → 다음 사냥터
        if now - self.hunt_started > cfg.get("hunt_minutes", 150) * 60:
            self.ground_idx += 1
            return "RETREAT", "사냥 시간 종료: 다음 사냥터"
        # 5) ATS 정지 감지(화면 정지) → 재시작
        frame = view["_frame"]
        if self.screen_stalled(frame):
            self.ats_start()
        return "HUNT", f"감시 HP={hp:.2f}"

    def screen_stalled(self, frame):
        """연속 정지 화면 = ATS 멈춤. 간단 프레임 차분."""
        if self._prev_frame is None:
            self._prev_frame = frame
            return False
        diff = cv2.absdiff(frame, self._prev_frame).max()
        self._prev_frame = frame
        return diff < 4

    _prev_frame = None

    def run_retreat(self, view):
        """귀환 주문서 사용 → 마을 확인."""
        self.click(*self.cfg["return_scroll"])
        time.sleep(5.0)
        home = self.read()
        if home and home["safe_zone"]:
            self.log_cycle()
            return "SUPPLY", "귀환 완료"
        return "RETREAT", "귀환 미확인: 재시도"

    def run_recover(self, view):
        """사망 처리: 원인 기록, 같은 사냥터 연속 사망이면 강등."""
        name = self.cfg.get("hunting_grounds", [{}])[self.ground_idx % max(1, len(self.cfg.get("hunting_grounds", [1])))].get("name", "?")
        self.deaths_at_ground[name] = self.deaths_at_ground.get(name, 0) + 1
        if self.deaths_at_ground.get(name, 0) >= 2:
            self.ground_idx += 1
            self.deaths_at_ground[name] = 0
            reason = f"{name} 연속 사망: 강등"
        else:
            reason = f"{name} 사망 1회: 보급 후 재시도"
        self.log_cycle(death=True)
        return "SUPPLY", reason

    HANDLERS = {"BOOT": run_boot, "SUPPLY": run_supply, "BUFF": run_buff,
                "TRAVEL": run_travel, "HUNT": run_hunt, "RETREAT": run_retreat,
                "RECOVER": run_recover}

    def step(self):
        view = self.read()
        handler = self.HANDLERS[self.state]
        new_state, message = handler(self, view)
        if new_state != self.state:
            logging.info("상태 전이 %s → %s (%s)", self.state, new_state, message)
        self.state = new_state
        return message

    def log_cycle(self, death=False):
        grounds = self.cfg.get("hunting_grounds", [])
        name = grounds[self.ground_idx % len(grounds)]["name"] if grounds else "?"
        record = {"t": time.time(), "ground": name,
                  "minutes": round((time.monotonic() - self.hunt_started) / 60, 1),
                  "potions": self.stats["potions"], "death": death}
        with LOG_PATH.open("a", encoding="utf-8") as sink:
            sink.write(json.dumps(record, ensure_ascii=False) + "\n")


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
                break
            message = bot.step()
            logging.info("[%s] %s", bot.state, message)
            time.sleep(args.interval)
    finally:
        window.close()


if __name__ == "__main__":
    main()
