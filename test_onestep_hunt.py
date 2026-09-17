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
                patch.object(oh, "NOMOUSE", Path("/nonexistent/nomouse")), \
                patch.object(oh, "PotionKeys", return_value=potion), \
                patch.object(oh, "hp_read", side_effect=hp_read), \
                patch.object(oh, "find_character", return_value=(5, 5)), \
                patch.object(oh, "red_name_candidates", return_value=[]), \
                patch.object(oh, "mob_hp_bars", return_value=[]), \
                patch.object(oh, "in_play_rect", return_value=True), \
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


class HoldSwingTests(unittest.TestCase):
    """BTS-1033742: 전투 중 재클릭하면 칼질이 끊긴다."""

    def test_노란막대면_재클릭_홀드(self):
        frame = object()
        with patch.object(oh, "mob_hp_bars", return_value=[(100, 200, 40)]):
            self.assertTrue(oh.should_hold_swing(frame, None, 10.0))

    def test_막대없고_클릭쿨지나면_홀드안함(self):
        frame = object()
        with patch.object(oh, "mob_hp_bars", return_value=[]):
            self.assertFalse(oh.should_hold_swing(frame, 0.0, 7.0))

    def test_hud_캐릭터_오탐은_play_중심(self):
        left, top, width, height = oh.PLAY_RECT
        with patch.object(oh, "find_character", return_value=(1881, 388, 0.0)):
            got = oh.hunt_character(object())
        self.assertEqual(got[0], left + width // 2)
        self.assertEqual(got[1], top + height // 2)
        with patch.object(oh, "find_character", return_value=(800, 500, 0.9)):
            self.assertEqual(oh.hunt_character(object())[0], 800)

    def test_클릭직후면_막대없어도_홀드(self):
        frame = object()
        with patch.object(oh, "mob_hp_bars", return_value=[]):
            self.assertTrue(oh.should_hold_swing(frame, 9.5, 10.0))

    def test_play_rect_밖은_사냥클릭_금지(self):
        left, top, width, height = oh.PLAY_RECT
        self.assertTrue(oh.in_play_rect(left + 10, top + 10))
        self.assertFalse(oh.in_play_rect(1916, 507))
        self.assertFalse(oh.in_play_rect(left - 1, top + 10))
        self.assertFalse(oh.in_play_rect(left + width, top + 10))

    def test_노란막대면_메인루프가_클릭하지_않는다(self):
        w, _ = HpUnreadableTests()._run([0.9, 0.9, 0.9])
        # _run은 막대 없음. 막대가 있으면 클릭 생략.
        w2 = MagicMock()
        w2.active.return_value = True
        w2.capture.return_value = MagicMock(shape=(10, 10, 3))
        potion = MagicMock(); potion.check.return_value = None
        hp_iter = iter([0.9, 0.9, 0.9])

        def hp_read(_):
            try:
                return next(hp_iter)
            except StopIteration:
                raise SystemExit

        stop = MagicMock(); stop.exists.return_value = False
        ext = MagicMock(); ext.read.return_value = None
        with patch.object(oh, "CdpWindow", return_value=w2), \
                patch.object(oh, "ExtHpSource", return_value=ext), \
                patch.object(oh, "calibrate_hud", return_value=(100, 253)), \
                patch.object(oh, "PotionKeys", return_value=potion), \
                patch.object(oh, "hp_read", side_effect=hp_read), \
                patch.object(oh, "find_character", return_value=(800, 500)), \
                patch.object(oh, "red_name_candidates", return_value=[]), \
                patch.object(oh, "mob_hp_bars", return_value=[(900, 400, 50)]), \
                patch.object(oh, "near_mobs", return_value=[(900, 400, 200)]), \
                patch.object(oh, "user_active", return_value=False), \
                patch.object(oh.time, "sleep"), \
                patch.object(oh, "STOP", stop), \
                patch.object(oh, "log"):
            oh.main()
        w2.click.assert_not_called()


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

    def test_read는_확장_ratio_우선(self):
        src = oh.ExtHpSource(url="http://x/hp")
        with patch.object(src, "_fetch", return_value={"ratio": 0.84}):
            self.assertAlmostEqual(src.read(), 0.84)
        with patch.object(src, "_fetch", return_value={"hp": 213, "hp_max": 253}):
            self.assertAlmostEqual(src.read(), 213 / 253)
        with patch.object(src, "_fetch", return_value=None):
            self.assertIsNone(src.read())

    def test_read는_가드없는_원시값(self):
        # 가드는 read_hp_source의 hp_guard로 경로 통합 — 이중 상태 어긋남
        # 방지. read 자체는 원시값을 돌려준다.
        src = oh.ExtHpSource(url="http://x/hp")
        with patch.object(src, "_fetch", return_value={"ratio": 0.94}):
            self.assertAlmostEqual(src.read(), 0.94)
        with patch.object(src, "_fetch", return_value={"ratio": 0.09}):
            self.assertAlmostEqual(src.read(), 0.09)

    def test_hp_guard_오독_유저보_오염_없이(self):
        # '223'→'23' 오독(0.09) 첫 프레임은 직전값 유보(prev 오염 없음),
        # 다음 정상값은 그대로 통과된다(2차 사고: 오독이 prev를 덮어써
        # 한 프레임 늦게 노출되던 결함 차단).
        oh._HP_GUARD["last"] = None
        oh._HP_GUARD["streak"] = 0
        self.assertAlmostEqual(oh.hp_guard(0.94), 0.94)
        self.assertAlmostEqual(oh.hp_guard(0.09), 0.94)   # 유보
        self.assertAlmostEqual(oh.hp_guard(0.85), 0.85)   # 정상 통과(오염 없음)
        self.assertIsNone(oh.hp_guard(None))
        oh._HP_GUARD["last"] = None
        oh._HP_GUARD["streak"] = 0

    def test_hp_guard_진짜_급변은_연속2회_승인(self):
        oh._HP_GUARD["last"] = None
        oh._HP_GUARD["streak"] = 0
        self.assertAlmostEqual(oh.hp_guard(0.94), 0.94)
        self.assertAlmostEqual(oh.hp_guard(0.30), 0.94)   # 첫 급락 유보
        self.assertAlmostEqual(oh.hp_guard(0.28), 0.28)   # 연속 → 승인
        oh._HP_GUARD["last"] = None
        oh._HP_GUARD["streak"] = 0


class CalibrateHudTests(unittest.TestCase):
    """사냥 진입 전 HUD 확보 게이트(사용자 지시: 막대를 파악하고 진입)."""

    def _run(self, seq):
        src = MagicMock()
        src.read.return_value = None  # probe 경로(숫자 일관)를 검증
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
