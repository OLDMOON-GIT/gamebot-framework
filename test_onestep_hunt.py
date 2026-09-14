"""onestep_hunt 안전장치 — 사용자 양보 강행 금지, HP 판독 불가 시 공격 보류."""
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import onestep_hunt as oh


class YieldClickTests(unittest.TestCase):
    def test_user_busy_never_forces_click(self):
        """사용자가 계속 조작 중이면 한도 뒤 클릭을 강행하지 않고 UserBusy."""
        w = MagicMock()
        with patch.object(oh, "user_active", return_value=True), \
                patch.object(oh.time, "sleep"), \
                patch.object(oh, "STOP", Path("/nonexistent/stop")):
            with self.assertRaises(oh.UserBusy):
                oh.yield_click(w, 1, 2, max_wait=6)
        w.click.assert_not_called()

    def test_click_after_user_releases(self):
        """사용자가 손을 떼면 그때 클릭한다."""
        w = MagicMock()
        w.geometry.return_value = (0, 0, 10, 10)
        with patch.object(oh, "user_active", side_effect=[True, True, False]), \
                patch.object(oh.time, "sleep"), \
                patch.object(oh, "STOP", Path("/nonexistent/stop")):
            oh.yield_click(w, 1, 2, max_wait=120)
        w.click.assert_called_once_with(1, 2, (0, 0, 10, 10))


class HpUnreadableTests(unittest.TestCase):
    def _run(self, hp_values):
        """루프를 hp 시퀀스만큼 돌리고 클릭/물약 호출 여부를 돌려준다."""
        w = MagicMock()
        w.active.return_value = True
        w.capture.return_value = MagicMock(shape=(10, 10, 3))
        potion = MagicMock()
        potion.check.return_value = None
        hp_iter = iter(hp_values)

        def hp_read(_):
            try:
                return next(hp_iter)
            except StopIteration:
                raise SystemExit

        stop = MagicMock(); stop.exists.return_value = False
        with patch.object(oh, "CdpWindow", return_value=w), \
                patch.object(oh, "PotionKeys", return_value=potion), \
                patch.object(oh, "hp_read", side_effect=hp_read), \
                patch.object(oh, "find_character", return_value=(5, 5)), \
                patch.object(oh, "red_name_candidates", return_value=[]), \
                patch.object(oh, "near_mobs", return_value=[(3, 3, 9)]), \
                patch.object(oh, "user_active", return_value=False), \
                patch.object(oh.time, "sleep"), \
                patch.object(oh, "STOP", stop), \
                patch.object(oh, "log"):
            oh.main()
        return w, potion

    def test_hp_none_holds_attack_and_potion(self):
        """HP None 이면 몹 클릭도 물약도 하지 않는다."""
        w, potion = self._run([None, None, None])
        w.click.assert_not_called()
        potion.check.assert_not_called()

    def test_hp_none_persist_stops(self):
        """12회 연속 판독 불가면 사망 방지로 루프 종료(그 뒤 hp 가 와도 클릭 없음)."""
        w, _ = self._run([None] * 12 + [0.9, 0.9])
        w.click.assert_not_called()

    def test_hp_read_resumes_attack(self):
        """판독이 돌아오면 카운터 리셋 후 정상 공격."""
        w, _ = self._run([None, 0.9, 0.9, 0.9])
        self.assertTrue(w.click.called)


if __name__ == "__main__":
    unittest.main()
