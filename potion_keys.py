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

from linux_vision import hp_read, note_recovery
from user_gate import user_active

POTION_HP = 0.80      # 사용자 지정 임계: 80% 미만이면 물약
CONFIRM_GAP = 0.5     # 2프레임 확인 최소 간격(초)
POTION_WAIT = 1.5     # 키 입력 후 재판독까지 대기(초)
COOLDOWN = 3.0        # 물약 연타 방지 쿨다운(초)
GAIN_MIN = 0.04       # 재판독에서 '올랐다'로 인정할 최소 상승 폭
DRY_LIMIT = 3         # 연속 무반응 허용 턴 수(넘으면 재고 소진)

USED = "used"          # 물약을 사용한 턴
SKIP = "skip"          # 임계 이상이라 물약 없음
UNKNOWN = "unknown"    # HP 판독 불가 — 물약 보류
EXHAUSTED = "exhausted"  # F5/F6 모두 무반응 누적 — 재고 소진 추정


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class PotionKeys:
    """봇 루프마다 check(window, hp)를 한 번 부른다."""

    def __init__(self, threshold=POTION_HP):
        self.threshold = threshold
        self._last_used = 0.0
        self._low_since = None    # 임계 미만 관측 시작 시각(2프레임 확인)
        self._first_key = "F5"    # 먼저 누를 키(마지막으로 성공한 키)
        self._dry = 0             # 연속 무반응 턴 수

    def _yield_gate(self):
        """사용자가 마우스를 쓰는 동안 키 입력을 양보한다."""
        waited = 0
        while user_active() and waited < 120:
            time.sleep(2.0)
            waited += 2

    def _press(self, window, name):
        self._yield_gate()
        window.key(name, window.geometry())

    def _try_key(self, window, name, hp):
        """키 하나를 누르고 재판독해 반응 여부를 돌려준다."""
        self._press(window, name)
        # BTS-1033358: 판독기의 HP 급상승 가드를 면제시킨다. 알리지 않으면
        # 물약이 실제로 들어가도 상승분이 한 프레임 유보되어 gained=False가
        # 되고, 없는 '무반응'을 근거로 두 번째 키까지 눌러 물약을 2개 쓴다.
        note_recovery(POTION_WAIT + 2.0)
        time.sleep(POTION_WAIT)
        hp_after = hp_read(window.capture())
        gained = hp_after is not None and hp_after > hp + GAIN_MIN
        return gained, hp_after

    def check(self, window, hp):
        """물약이 필요하면 (2프레임 확인 후) F5/F6을 누른다.

        반환값: USED / SKIP / UNKNOWN / EXHAUSTED. EXHAUSTED를 받은 봇은
        사망 방지를 위해 사냥을 중단한다(hunt_map 종전 동작 승계).
        """
        if hp is None:
            log("HP 판독 불가 — 물약 보류")
            self._low_since = None
            return UNKNOWN
        if hp >= self.threshold:
            self._low_since = None
            return SKIP
        now = time.monotonic()
        if self._low_since is None:          # 1프레임째: 기록만
            self._low_since = now
            return SKIP
        if now - self._low_since < CONFIRM_GAP or now - self._last_used < COOLDOWN:
            return SKIP
        self._low_since = None
        self._last_used = now

        second = "F6" if self._first_key == "F5" else "F5"
        gained, hp_after = self._try_key(window, self._first_key, hp)
        if gained:
            self._dry = 0
            log(f"물약 {self._first_key} (HP {hp:.2f}→{hp_after:.2f})")
            return USED
        gained, hp_after = self._try_key(window, second, hp)
        if gained:
            self._first_key = second
            self._dry = 0
            log(f"물약 {self._first_key} (HP {hp:.2f}→{hp_after:.2f}, "
                f"첫 키 무반응 폴백)")
            return USED
        self._dry += 1
        log(f"물약 무반응 F5/F6 ({self._dry}/{DRY_LIMIT}, HP {hp:.2f})")
        if self._dry >= DRY_LIMIT:
            log("물약 재고 소진 추정 — 사냥 중단 권고")
            return EXHAUSTED
        return USED
