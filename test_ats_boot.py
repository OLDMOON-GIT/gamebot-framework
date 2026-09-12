"""ATS 기동 루프 검증 — 템플릿 미매칭 시 좌표 추정 클릭 금지."""
import unittest
from unittest.mock import patch

import ats_boot
from ats_boot import AtsBoot
from ats_probe import ON, UNKNOWN


class FakeWindow:
    def __init__(self, frames):
        self.frames = list(frames)
        self.clicks = []

    def active(self):
        return True

    def capture(self):
        # 2026-09-09: assets/ui/action_btn.png가 실재하게 되어 문자열
        # 프레임이면 find_button이 frame.shape 접근에서 죽는다. 실제 배열을
        # 돌려준다(검은 화면 = 매칭 실패 = 클릭 없음, 원래 취지 유지).
        import numpy as np
        if self.frames:
            self.frames.pop(0)
        return np.zeros((1332, 1933, 3), dtype=np.uint8)

    def geometry(self):
        return (0, 0, 1933, 1332)

    def click(self, x, y, geo):
        self.clicks.append((x, y))


CFG = {"ats_time_reader": [1, 2, 3, 4]}


class BootTests(unittest.TestCase):
    def test_missing_template_never_clicks(self):
        """템플릿이 없으면 클릭 0회 — 고정 좌표 폐기 원칙."""
        win = FakeWindow(["f"] * 10)
        boot = AtsBoot(win, CFG)
        with patch.object(ats_boot, "BOOT_BUDGET", 1), \
                patch.object(boot.probe, "observe", return_value=UNKNOWN):
            result = boot.boot()
        self.assertEqual(result, UNKNOWN)
        self.assertEqual(win.clicks, [])  # 어떤 클릭도 나가지 않는다

    def test_boot_success_on_countdown(self):
        """카운트다운 감소가 확인되면 ON, 기동 클릭은 시도된다."""
        win = FakeWindow(["f"] * 30)
        boot = AtsBoot(win, CFG)
        # 1스텝: UNKNOWN → 기동 시도(템플릿 매칭 성공 가정) → 검증 중 ON
        with patch.object(boot.probe, "observe",
                          side_effect=[UNKNOWN, UNKNOWN, ON]), \
                patch.object(ats_boot, "VERIFY_TIMEOUT", 0.1), \
                patch.object(boot, "try_start", return_value=True) as tried:
            result = boot.boot()
        self.assertEqual(result, ON)
        tried.assert_called_once()


if __name__ == "__main__":
    unittest.main()
