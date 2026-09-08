"""ATS 탐침 판정 검증 — 카운트다운 감소만 ON, 그 외 전부 UNKNOWN."""
import unittest
from unittest.mock import patch

import ats_probe
from ats_probe import AtsProbe, ON, UNKNOWN


def fake_frame(seconds):
    return {"seconds": seconds}  # read_ats_seconds를 patch해 쓰는 표식


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.probe = AtsProbe((1, 2, 3, 4))

    def observe(self, seconds, advance=5.0):
        with patch.object(ats_probe.time, "monotonic",
                          side_effect=lambda: self._t), \
             patch.object(ats_probe, "read_ats_seconds", return_value=seconds):
            self._t += advance
            return self.probe.observe(fake_frame(seconds))

    def test_decreasing_is_on(self):
        self._t = 100.0
        self.assertEqual(self.observe(300), UNKNOWN)  # 샘플 1개
        self.assertEqual(self.observe(299), ON)       # 감소 = ON

    def test_equal_or_unreadable_is_unknown(self):
        """값이 같거나 판독 불가면 ON 단정 금지(무인 운전 금지 원칙)."""
        self._t = 100.0
        self.observe(300)
        self.assertEqual(self.observe(300), UNKNOWN)  # 정지 카운터
        self.assertEqual(self.observe(None), UNKNOWN)  # 판독 불가

    def test_too_close_samples_unknown(self):
        """간격 1초 미만 샘플로는 판정하지 않는다."""
        self._t = 100.0
        self.observe(300)
        self.assertEqual(self.observe(299, advance=0.5), UNKNOWN)

    def test_increase_is_unknown(self):
        """값이 늘어나면(오판/충전) ON이 아니다."""
        self._t = 100.0
        self.observe(300)
        self.assertEqual(self.observe(310), UNKNOWN)

    def test_no_rect_is_unknown(self):
        """ROI 미실측이면 절대 판정하지 않는다."""
        probe = AtsProbe(None)
        self.assertEqual(probe.observe(fake_frame(1)), UNKNOWN)


if __name__ == "__main__":
    unittest.main()
