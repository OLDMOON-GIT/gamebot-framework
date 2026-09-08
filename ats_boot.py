"""ATS 기동 검증 루프 — 클릭하고 '정말 켜졌는지' 검증하고, 안 켜지면 다음 수.

Claude 협의(2026-09-09) 절차:
  probe OFF/UNKNOWN 상태에서
  → 템플릿으로 행동창 버튼 찾아 클릭 → 자동사냥 메뉴 → 시작
  → 잔여시간 카운트다운 감소(=ON) 확인까지 대기
  → 예산(시도 횟수) 소진 시 사람에게 알리고 정지(halt). 상태 불명 운전 금지.
"""

import logging
import time

from ats_probe import AtsProbe, ON, UNKNOWN
from ui_finder import find_button

BOOT_BUDGET = 5          # 최대 기동 시도 횟수(협의안: 예산 소산 → 사람 개입)
VERIFY_TIMEOUT = 12.0    # 클릭 후 ON 판정 대기(초)
CLICK_GAP = 1.2


class AtsBoot:
    def __init__(self, window, config):
        self.window = window
        self.cfg = config
        rect = config.get("ats_time_reader")
        self.probe = AtsProbe(rect)

    def _click_found(self, frame, template_name):
        """템플릿으로 버튼을 찾아 클릭. 못 찾으면 False(좌표 추정 클릭 금지)."""
        found = find_button(frame, template_name)
        if not found:
            return False
        x, y, score = found
        logging.info("%s 매칭 (%.2f) 클릭", template_name, score)
        self.window.click(x, y, self.window.geometry())
        return True

    def try_start(self, frame):
        """한 번의 기동 시도: 행동창→자동사냥→시작. 템플릿 없음/미매칭은 실패."""
        ok = True
        for step in ("action_btn", "ats_menu", "ats_start"):
            if not self._click_found(frame, step):
                logging.warning("템플릿 미매칭: %s — 기동 중단(좌표 추정 금지)", step)
                return False
            time.sleep(CLICK_GAP)
            try:
                frame = self.window.capture()
            except (RuntimeError, OSError):
                ok = False
                break
        return ok

    def boot(self):
        """검증 루프: ON 확정까지 반복. 반환 ON/UNKNOWN(예산 소진)."""
        for attempt in range(1, BOOT_BUDGET + 1):
            try:
                if not self.window.active():
                    time.sleep(5)
                    continue
                frame = self.window.capture()
            except (RuntimeError, OSError):
                time.sleep(5)
                continue
            state = self.probe.observe(frame)
            if state == ON:
                return ON
            logging.info("기동 시도 %d/%d (현재 상태=%s)", attempt, BOOT_BUDGET, state)
            if not self.try_start(frame):
                logging.warning("기동 불가(템플릿 부재) — 실측 필요")
                break
            deadline = time.monotonic() + VERIFY_TIMEOUT
            verified = False
            while time.monotonic() < deadline:
                time.sleep(2.5)
                try:
                    check = self.window.capture()
                except (RuntimeError, OSError):
                    continue
                if self.probe.observe(check) == ON:
                    verified = True
                    break
            if verified:
                logging.info("ATS 기동 확인(카운트다운 감소)")
                return ON
            logging.warning("기동 검증 실패(잔여시간 미감소) — 재시도")
        logging.error("ATS 기동 예산 소진 — 사람 확인 필요(스크린샷 저장)")
        try:
            import cv2
            cv2.imwrite("/tmp/linc-cycle/boot-fail.png", self.window.capture())
        except (RuntimeError, OSError, cv2.error):
            pass
        return UNKNOWN

    def keep_alive_step(self, frame):
        """감시 1스텝: ON이면 유지, UNKNOWN 지속이면 재기동 판단 재료 반환."""
        return self.probe.observe(frame)
