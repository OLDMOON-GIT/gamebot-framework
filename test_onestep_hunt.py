"""onestep_hunt 안전장치 — 사용자 양보 강행 금지, HP 판독 불가 시 공격 보류."""
import json
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
        ext = MagicMock()
        ext.read.return_value = None   # 확장 read는 폴백(기존 hp_read 경로)
        with patch.object(oh, "CdpWindow", return_value=w), \
                patch.object(oh, "ExtHpSource", return_value=ext), \
                patch.object(oh, "calibrate_hud", return_value=(100, 253)), \
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


class ExtHpSourceTests(unittest.TestCase):
    """BTS-1033471: 확장 네이티브 /hp 소스 — 형식 검증과 실패 처리."""

    def _probe(self, payload, raises=False):
        src = oh.ExtHpSource(url="http://x/hp")
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode()
        ctx = patch.object(oh.urllib.request, "urlopen",
                           side_effect=OSError("down") if raises
                           else MagicMock(return_value=resp))
        # urlopen은 컨텍스트 매니저로 쓰인다.
        if not raises:
            resp_ctx = MagicMock()
            resp_ctx.__enter__.return_value = resp
            ctx = patch.object(oh.urllib.request, "urlopen",
                               return_value=resp_ctx)
        with ctx:
            return src.probe()

    def test_정상_payload(self):
        self.assertEqual(self._probe({"hp": 213, "hp_max": 253}), (213, 253))

    def test_null_hp는_none(self):
        self.assertIsNone(self._probe({"hp": None, "hp_max": None}))

    def test_cur이_max_초과면_none(self):
        self.assertIsNone(self._probe({"hp": 300, "hp_max": 253}))

    def test_네트워크_실패는_none(self):
        self.assertIsNone(self._probe(None, raises=True))

    def test_read는_비율_반환(self):
        src = oh.ExtHpSource(url="http://x/hp")
        with patch.object(src, "probe", return_value=(213, 253)):
            self.assertAlmostEqual(src.read(), 213 / 253)
        with patch.object(src, "probe", return_value=None):
            self.assertIsNone(src.read())


class CalibrateHudTests(unittest.TestCase):
    """사냥 진입 전 HUD 확보 게이트(사용자 지시: 막대를 파악하고 진입)."""

    def _run(self, seq):
        src = MagicMock()
        src.probe.side_effect = seq
        stop = MagicMock(); stop.exists.return_value = False
        with patch.object(oh.time, "sleep"), \
                patch.object(oh, "STOP", stop):
            return oh.calibrate_hud(src, need=3, tries=8)

    def test_연속3회_일관되면_진입_승인(self):
        self.assertEqual(self._run([(200, 253)] * 3), (200, 253))

    def test_hp_max가_바뀌면_스트릭_리셋(self):
        # 253→244 로 분모가 흔들리면 오독으로 보고 다시 3회를 요구한다.
        # 리셋 뒤 244가 3회 연속이면 그때 승인(레벨업 등 실제 변화 수용).
        self.assertEqual(self._run([(200, 253), (200, 253), (200, 244),
                                    (200, 244), (200, 244)]), (200, 244))
        self.assertIsNone(self._run([(200, 253), (200, 253), (200, 244),
                                     (200, 244), None, None, None, None]))

    def test_중간_실패가_끼면_진입_거부(self):
        self.assertIsNone(self._run([(200, 253), None, (200, 253),
                                     (200, 253), None, None, None, None]))

    def test_전부_실패면_none(self):
        self.assertIsNone(self._run([None] * 8))

    def test_calibrate_cdp도_연속3회_필요(self):
        w = MagicMock()
        w.capture.return_value = MagicMock()
        stop = MagicMock(); stop.exists.return_value = False
        with patch.object(oh, "hp_read", side_effect=[0.9, None, 0.9, 0.9, 0.9]), \
                patch.object(oh.time, "sleep"), \
                patch.object(oh, "STOP", stop):
            self.assertAlmostEqual(oh.calibrate_cdp(w, need=3, tries=6), 0.9)


if __name__ == "__main__":
    unittest.main()
