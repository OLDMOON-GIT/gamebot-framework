"""물약 F5/F6 키 사용 — 봇 공용 상태 관리 (BTS-1033250).

사용자 지시(2026-09-12): HP 80% 미만이면 F5, 반응 없으면 F6.
BTS-1033250 실측: F6 = 물약(수량 1011→1010 확인), F5 = 빈 슬롯이었으나
슬롯 배치는 바뀔 수 있어 성공한 키를 기억하고 무반응 시 나머지 키로
폴백한다. 종전 퀵슬롯 클릭 경로(좌표 하드코딩/자동 학습)는 전부 폐지.

규칙:
- 행동은 2프레임 연속 임계 미만일 때만(한 프레임 OCR 오독으로 물약·
  귀환을 발사하지 않는다. 확인 간격 최소 0.5초).
- 키 입력 → 1.5초 대기 → 재판독 → HP가 오르지 않으면 나머지 키.
- 3초 쿨다운으로 연타(한 턴에 알 여러 개)를 막는다.
- hp None이면 누르지 않는다 — 모르면 추측하지 않는다.
- F5/F6 모두 무반응이 3턴 누적되면 재고 소진으로 본다(EXHAUSTED).
"""
import time

from bot_settings import load as load_settings

from user_gate import user_active  # 테스트 patch 호환(양보 게이트는 제거됨)

from linux_vision import hp_read, note_recovery


POTION_HP = 0.80      # 사용자 지정 임계: 80% 미만이면 물약
CONFIRM_GAP = 0.35    # 2프레임 확인 최소 간격(초) — 속도/오독 방어 타협
POTION_WAIT = 0.5     # 키 입력 후 재판독까지 대기(초) — 연속 투입 체감 2초→1초 미만(2026-09-15)
COOLDOWN = 1.2        # 턴 간 쿨다운(초) — 게임 물약 재사용 대기 수준(2026-09-15 사용자 지시 '빨라')
DANGER_COOLDOWN = 1.2  # 위험 구간(<0.45) 쿨다운 — 급할 때 빠르게(2026-09-15 사용자 지시)
CHAIN_MAX = 4          # 한 턴 연속 투입 상한(피가 많이 딸리면 여러 번: 사용자 지시)
# 비상 귀환(사용자 지시 2026-09-15): '물약이 아예없거나 20퍼미만의 경우 f8'
# — F8은 귀환 주문서다. HP<20% 또는 일반 물약(F5/F6) 소진 시 눌러 마을로
# 귀환한다. 귀환 성공 여부와 무관하게 사냥은 중단이 안전하다.
EMERGENCY_RETURN_KEY = "F8"
EMERGENCY_HP = 0.20
CHAIN_GAP = 0.6        # 연속 투입 간격 — 게임 물약 쿨다운 실측(~0.6s) 정합
POTION_GAIN = 0.08     # 물약 1개 회복량(2026-09-15 조사: 145건 실측 중앙
                       # +8%p, 현재 F5/F6 슬롯 소회복 물약 기준)
GAIN_MIN = 0.02       # 재판독 상승 인정 최소폭 — 소회복 물약도 인정(2026-09-15)
DRY_LIMIT = 3         # 연속 무반응 허용 턴 수(넘으면 재고 소진)

USED = "used"          # 물약을 사용한 턴
SKIP = "skip"          # 임계 이상이라 물약 없음
UNKNOWN = "unknown"    # HP 판독 불가 — 물약 보류
EXHAUSTED = "exhausted"  # F5/F6 모두 무반응 누적 — 재고 소진 추정
RETURN = "return"      # F8 귀환 주문서 사용 — 사냥 중단(마을)


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class PotionKeys:
    """봇 루프마다 check(window, hp)를 한 번 부른다."""

    def __init__(self, threshold=POTION_HP, read=None):
        self.threshold = threshold
        # HP 이력: 감소율 추정(사용자 지시 2026-09-15 '피가 줄어드는 속도에
        # 따라 빨아야됨') — 다구리로 빨리 줄수록 더 높은 HP에서 미리 투입.
        self._hp_hist = []   # [(monotonic, hp)] 최근 관측
        self._last_used = 0.0
        self._low_since = None    # 임계 미만 관측 시작 시각(2프레임 확인)
        # 2026-09-14 실측: F6=물약(1011→1010 확인), F5=빈 슬롯. 초기값
        # F5는 사용자 수동 물약/재생 상승분을 'F5 성공'으로 오판해 학습을
        # 오염시켰다(2026-09-15 사고) — 검증된 F6을 우선 키로 둔다.
        self._first_key = "F6"
        self._dry = 0             # 연속 무반응 턴 수
        self._read = read
        # 회복량 자동 학습(사용자 지시 '물약 종류에 따라 몇개 빨아야되는지
        # 계산'): 종류(빨갱이/맑은이 등)마다 회복량이 다르므로 매 투입의
        # 실측 증가량을 EMA로 학습해 필요 개수를 계산한다. 초기값은
        # 2026-09-15 145건 조사 중애 +8%p(HP 20).
        self._gain = POTION_GAIN
        self._alt_key = "F5"
        self._return_key = "F8"
        self._chain_max = CHAIN_MAX
        self._danger = EMERGENCY_HP
        self._recover_to = POTION_HP
        self._apply_settings()

    def _press(self, window, name):
        # 물약 키(F5/F6)는 마우스와 무관한 게임 키 입력이다. 종전 양보
        # 게이트(2026-09-15 사용자 수동 전투 중 실측)는 사용자의 마우스/
        # 키보드 활동으로 물약을 최대 120초 미뤄 사망 위험을 만들었다.
        # 몹 클릭(yield_click)만 양보하면 되고 물약은 즉시 발동한다.
        window.key(name, window.geometry())

    def _try_key(self, window, name, hp):
        """키 하나를 누르고 재판독해 반응 여부를 돌려준다."""
        self._press(window, name)
        # BTS-1033358: 판독기의 HP 급상승 가드를 면제시킨다. 알리지 않으면
        # 물약이 실제로 들어가도 상승분이 한 프레임 유보되어 gained=False가
        # 되고, 없는 '무반응'을 근거로 두 번째 키까지 눌러 물약을 2개 쓴다.
        note_recovery(POTION_WAIT + 2.0)
        time.sleep(POTION_WAIT)
        hp_after = (self._read(window) if self._read
                    else hp_read(window.capture()))
        gained = hp_after is not None and hp_after > hp + GAIN_MIN
        return gained, hp_after

    def _track(self, hp):
        """HP 이력 기록과 초당 감소율(하락만). 오독 스파이크는 가드를
        통과한 값이므로 관측 그대로 쓴다."""
        now = time.monotonic()
        self._hp_hist = [(t, v) for t, v in self._hp_hist if now - t <= 3.0]
        self._hp_hist.append((now, hp))
        if len(self._hp_hist) < 2:
            return None
        t0, v0 = self._hp_hist[0]
        t1, v1 = self._hp_hist[-1]
        dt = t1 - t0
        if dt < 0.3:
            return None
        drop = (v0 - v1) / dt
        return drop if drop > 0.005 else None

    def _threshold_now(self, drop_rate):
        """감소율 반영 임계: 초당 5%p씩 줄면 +0.05, 10%p면 +0.10 …
        상한 0.92 — 빨리 줄수록 그만큼 일찍 물약을 시작한다."""
        base = self.threshold
        if not drop_rate:
            return base
        return min(0.92, base + drop_rate)

    def _apply_settings(self):
        """확장 UI 설정 반영(키/임계/상한). load()는 5초 캐시라 매 턴
        호출해도 가볍다."""
        s = load_settings()
        self.threshold = s["potion_start_pct"] / 100.0
        # 물약 슬롯(사용자 지시 2026-09-15): 키 배치 + 종류별 회복량으로
        # 필요 개수를 계산한다. 위기(red_pct 밑)엔 crisis_potion(예: 붉은),
        # 평상엔 main_potion(예: 맑은). 학습 회복량(_gain)이 heal_pct를
        # 실측으로 보정한다.
        main = s.get("main_potion") or {}
        crisis = s.get("crisis_potion") or {}
        self._main_key = main.get("key") or "F5"
        self._main_gain = main.get("heal_pct", 8) / 100.0
        self._crisis_key = crisis.get("key") or ""
        self._crisis_gain = crisis.get("heal_pct", 0) / 100.0 or self._main_gain
        self._main_kind = main.get("kind", "")
        self._crisis_kind = crisis.get("kind", "")
        self._red_pct = s.get("red_pct", 45) / 100.0
        self._first_key = self._main_key
        self._alt_key = s["potion_key_alt"]
        self._return_key = s["return_key"]
        self._chain_max = s["chain_max"]
        self._danger = s["danger_pct"] / 100.0
        self._recover_to = s["recover_to_pct"] / 100.0
        return s.get("enabled", True)

    def check(self, window, hp):
        if not self._apply_settings():
            return SKIP
        """물약이 필요하면 (2프레임 확인 후) F5/F6을 누른다.

        반환값: USED / SKIP / UNKNOWN / EXHAUSTED. EXHAUSTED를 받은 봇은
        사망 방지를 위해 사냥을 중단한다(hunt_map 종전 동작 승계).
        """
        if hp is None:
            log("HP 판독 불가 — 물약 보류")
            self._low_since = None
            return UNKNOWN
        drop = self._track(hp)
        thr = self._threshold_now(drop)
        if drop and drop >= 0.1:
            log(f"HP 급감 {drop:.2f}/s — 임계 {thr:.2f} 상향")
        if hp >= thr:
            self._low_since = None
            return SKIP
        now = time.monotonic()
        if self._low_since is None:          # 1프레임째: 기록만
            self._low_since = now
            return SKIP
        cooldown = DANGER_COOLDOWN if hp < 0.45 else COOLDOWN
        if now - self._low_since < CONFIRM_GAP or now - self._last_used < cooldown:
            return SKIP
        self._low_since = None
        self._last_used = now

        # 비상 귀환(사용자 지시): HP<20%면 물약을 따질 새 없이 F8 귀환.
        # 단 F8은 되돌릴 수 없다(주문서 소모+이탈) — 발사 직전 재판독으로
        # 여전히 위험인지 2중 확인한다(2026-09-15 사고: 만피 오독→무반응
        # 3회→소진 오판→귀환까지 연쇄).
        if hp < self._danger:
            if self._read:
                rc = self._read(window)
                if rc is not None and rc >= EMERGENCY_HP:
                    log(f"귀환 직전 재확인 HP {rc:.2f} — 취소(오독 방어)")
                    return SKIP
            log(f"HP 위험({hp:.2f}) — {self._return_key} 귀환 주문서")
            window.key(self._return_key, window.geometry())
            return RETURN

        # 투입 직전 최종 확인(2026-09-15 만피 낭비 재발): 발사 순간 다시
        # 읽어 만피/회복됐으면 취소한다. 비용(판독 1회) < 물약 낭비.
        if self._read:
            recheck = self._read(window)
            if recheck is not None and recheck >= thr:
                log(f"투입 직전 회복 확인(HP {recheck:.2f}) — 취소")
                return SKIP

        # 키/회복량 선택: 위기엔 위기 슬롯(지정 시), 아니면 주 슬롯.
        if hp < self._red_pct and self._crisis_key:
            self._first_key = self._crisis_key
            self._gain = max(0.02, self._crisis_gain)
            kind = self._crisis_kind or "?"
        else:
            self._first_key = self._main_key
            self._gain = max(0.02, self._main_gain)
            kind = self._main_kind or "?"
        second = self._alt_key
        gained, hp_after = self._try_key(window, self._first_key, hp)
        if not gained:
            gained, hp_after = self._try_key(window, second, hp)
        if gained:
            self._dry = 0
            # 피가 많이 딸리면 여러 번(2026-09-15 사용자 지시): 투입 후에도
            # 임계 밑이면 게임 재사용 대기 후 연속 투입. CHAIN_MAX 상한.
            chain = 1
            base_hp = hp
            # 위기(사용자 지시 '40퍼 쭉쭉 내려가면 80 이상으로') 시작이
            # 낮으면 상한을 늘린다.
            limit = self._chain_max if hp >= 0.55 else self._chain_max + 2
            thr = max(thr, self._recover_to)
            while (hp_after is not None and hp_after < thr
                   and chain < limit):
                time.sleep(CHAIN_GAP)
                more, hp_next = self._try_key(window, self._first_key, hp_after)
                if not more:
                    break
                chain += 1
                hp_after = hp_next
            log(f"물약 {self._first_key} (HP {base_hp:.2f}→{hp_after:.2f}"
                f"{', 연속 ' + str(chain) + '개' if chain > 1 else ''}"
                f", 회복 {self._gain:.2f}/개)")
            # 턴을 마쳐도 임계 미달이면 쿨다운을 풀어 다음 폴링(0.5초)에
            # 즉시 재개한다 — 80% 이상 회복이 원칙(사용자 지시).
            if hp_after is not None and hp_after < thr:
                self._last_used = 0.0
            return USED
        self._dry += 1
        log(f"물약 무반응 F5/F6 ({self._dry}/{DRY_LIMIT}, HP {hp:.2f})")
        if self._dry >= DRY_LIMIT:
            # 일반 소진 — F8 귀환(사용자 지시: 사망 방지가 낫다).
            # 되돌릴 수 없는 행동: 직전 재판독으로 HP가 실제 낮은지 확인
            # (오독 무반응이 소진으로 보이는 사고 방어).
            if self._read:
                rc = self._read(window)
                if rc is not None and rc >= 0.60:
                    log(f"소진 판정 재확인 HP {rc:.2f} 안정 — 귀환 보류")
                    self._dry = 0
                    return SKIP
            log("물약 소진 — F8 귀환 주문서")
            window.key(self._return_key, window.geometry())
            return RETURN
        return USED
