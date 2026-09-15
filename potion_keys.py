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

from user_gate import user_active  # 테스트 patch 호환(양보 게이트는 제거됨)

from linux_vision import hp_read, note_recovery


POTION_HP = 0.80      # 사용자 지정 임계: 80% 미만이면 물약
CONFIRM_GAP = 0.35    # 2프레임 확인 간격(초) — 지연 단축(2026-09-16 사용자 지시)
POTION_WAIT = 1.0     # 키 입력 후 재판독 대기(초) — 게임 물약 쿨(~0.6s+)보다
                     # 짧으면 F5 효과 전 재판독으로 무반응 오판 → F6 이중 발사(2026-09-16 사고)
COOLDOWN = 3.0        # 물약 연타 방지 쿨다운(초)
DANGER_COOLDOWN = 1.2  # 위험 구간(<0.45) 쿨다운 — 급할 때 빠르게(2026-09-15 사용자 지시)
CHAIN_MAX = 4          # 한 턴 연속 투입 상한(피가 많이 딸리면 여러 번: 사용자 지시)
CHAIN_GAP = 1.2        # 연속 투입 간격(게임 물약 재사용 대기)
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

    def __init__(self, threshold=POTION_HP, read=None):
        self.threshold = threshold
        self._last_used = 0.0
        self._low_since = None    # 임계 미만 관측 시작 시각(2프레임 확인)
        # 2026-09-14 실측: F6=물약(1011→1010 확인), F5=빈 슬롯. 초기값
        # F5는 사용자 수동 물약/재생 상승분을 'F5 성공'으로 오판해 학습을
        # 오염시켰다(2026-09-15 사고) — 검증된 F6을 우선 키로 둔다.
        self._first_key = "F6"
        self._alt_key = "F5"
        self._crisis_key = ""
        self._red_pct = 0.45
        self._first_fail = 0
        self._f5_skip = 0
        self._dry = 0             # 연속 무반응 턴 수
        # HP 소스 주입(BTS-1033471): onestep_hunt가 확장 네이티브 판독
        # (ext_vision /hp) 우선 경로를 넘긴다. None이면 기존 CDP 판독.
        self._read = read

    def _press(self, window, name):
        # 물약 키(F5/F6)는 마우스와 무관한 게임 키 입력이다. 종전 양보
        # 게이트(2026-09-15 사용자 수동 전투 중 실측)는 사용자의 마우스/
        # 키보드 활동으로 물약을 최대 120초 미뤄 사망 위험을 만들었다.
        # 몹 클릭(yield_click)만 양보하면 되고 물약은 즉시 발동한다.
        window.key(name, window.geometry())

    _PROBE_KEYS = ("F7", "F8")

    def _probe_next(self, window, hp):
        """위기마다 미시험 키 1회 시험 — 빨간 물약(+15%p↑) 확정."""
        while self._probe_idx < len(self._PROBE_KEYS):
            key = self._PROBE_KEYS[self._probe_idx]
            self._probe_idx += 1
            gained, hp_after = self._try_key(window, key, hp)
            inc = (hp_after - hp) if (gained and hp_after) else 0
            if inc >= 0.28:
                log(f"감별: {key} +{inc:.0%}(≈{round(inc*253)}HP) — 맑은 계열(위기 물약)! 확정")
                try:
                    from bot_settings import load as _l, save as _sv
                    s = dict(_l(refresh=0))
                    s["crisis_potion"] = {"key": key, "kind": "빨간",
                                          "heal_pct": round(inc * 100)}
                    _sv(s)
                except Exception:
                    pass
                return True
            log(f"감별: {key} +{inc:.0%} — 다음 키")
            return True
        return False

    _probe_idx = 0

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

    def _apply_key_setting(self):
        """UI 설정(물약 슬롯)에서 주 물약 키만 반영 — 계산 로직은 스테이블
        유지(2026-09-15 사용자: UI는 아까 것, 동작은 안정)."""
        # 매 체크 로드(bot_settings 5초 캐시 — 가볍다). 주 키는 학습
        # 보존(초기 1회), 위기 키/위험 임계는 세팅값을 매번 따른다.
        try:
            from bot_settings import load as _ls
            s = _ls()
            k = (s.get("main_potion") or {}).get("key")
            if k:
                self._first_key = k   # 주 물약 우선 고정(사용자 지시 2026-09-16)
            self._crisis_key = (s.get("crisis_potion") or {}).get("key") or ""
            self._red_pct = s.get("red_pct", 45) / 100.0
            self._alt_key = s.get("potion_key_alt") or "F6"
        except Exception:
            pass

    def check(self, window, hp):
        self._apply_key_setting()
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
        cooldown = DANGER_COOLDOWN if hp < 0.45 else COOLDOWN
        if now - self._low_since < CONFIRM_GAP or now - self._last_used < cooldown:
            return SKIP
        self._low_since = None
        self._last_used = now

        # 세팅값 감별(사용자 지시): 위기(<red_pct)엔 지정한 위기 물약 키.
        # 미지정이면 자동 감별 — F7/F8를 위기마다 1회씩 시험.
        # 리니지 조사(네이버 정리): 빨간 6~27(주물약, F5 실측 +20),
        # 주홍 26~68, 맑은/엔트열매 44~107(평균 75). 위기 물약=맑은 계열
        # 확정 기준 **+28%p(≈71 HP)** — 주홍 최대 68과 분리.
        second = self._alt_key
        if hp < self._red_pct:
            if self._crisis_key:
                self._first_key = self._crisis_key
            elif self._probe_next(window, hp):
                return USED
        # 사용자 지시(2026-09-16): 무조건 F5부터 — 매 턴 F5 우선, 무반응인
        # 그 턴만 F6 폴백. F5 재고가 있으면 항상 F5가 먼저 발사된다.
        gained, hp_after = self._try_key(window, self._first_key, hp)
        if gained:
            self._first_fail = 0
        else:
            self._first_fail += 1
            gained, hp_after = self._try_key(window, second, hp)
            if gained:
                self._first_key = second
        if gained:
            self._dry = 0
            # 피가 많이 딸리면 여러 번(2026-09-15 사용자 지시): 투입 후에도
            # 임계 밑이면 게임 재사용 대기 후 연속 투입. CHAIN_MAX 상한.
            chain = 1
            base_hp = hp
            while (hp_after is not None and hp_after < self.threshold
                   and chain < CHAIN_MAX):
                time.sleep(CHAIN_GAP)
                more, hp_next = self._try_key(window, self._first_key, hp_after)
                if not more:
                    break
                chain += 1
                hp_after = hp_next
            log(f"물약 {self._first_key} (HP {base_hp:.2f}→{hp_after:.2f}"
                f"{', 연속 ' + str(chain) + '회' if chain > 1 else ''})")
            return USED
        self._dry += 1
        log(f"물약 무반응 F5/F6 ({self._dry}/{DRY_LIMIT}, HP {hp:.2f})")
        if self._dry >= DRY_LIMIT:
            log("물약 재고 소진 추정 — 사냥 중단 권고")
            return EXHAUSTED
        return USED
