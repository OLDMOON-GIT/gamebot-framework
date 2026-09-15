"""potion_keys F5/F6 물약 회귀 (BTS-1033250).

코칭 스펙(2026-09-13):
- 경계: 0.79 → 누름, 0.81 → 안 누름(사용자 임계 80%).
- 행동은 2프레임 연속 임계 미만일 때만.
- F5 → 1.5s → 재판독 → 안 오르면 F6.
- 3초 쿨다운(연타 방지). hp None이면 절대 누르지 않는다.
- F5/F6 모두 무반응 3턴 → 재고 소진(EXHAUSTED).
"""
import unittest
from unittest.mock import Mock, patch

import potion_keys
import bot_settings
from unittest.mock import patch as _patch
from potion_keys import COOLDOWN, EXHAUSTED, SKIP, UNKNOWN, USED, PotionKeys


class TestPotionKeys(unittest.TestCase):
    def setUp(self):
        _p = _patch.object(bot_settings, "PATH", "/nonexistent/settings.json")
        _p.start(); self.addCleanup(_p.stop)
        bot_settings._cache["t"] = 0.0
        self.w = Mock()
        self.w.geometry.return_value = (0, 0, 1933, 1332)

    def _potion(self, reread=None):
        """양보 게이트 통과 + 재판독(hp_read) 고정 + sleep 무시."""
        p = PotionKeys()
        patchers = [
            patch.object(potion_keys, "user_active", return_value=False),
            patch.object(potion_keys.time, "sleep"),
            patch.object(potion_keys, "hp_read",
                         reread or (lambda img: 0.95)),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        return p

    def _armed(self, p, hp):
        """2프레임째 호출을 시뮬레이트(확인 간격은 시간 의존이라 과거로)."""
        first = p.check(self.w, hp)
        assert first == SKIP, first  # 1프레임째: 기록만
        p._low_since -= potion_keys.CONFIRM_GAP + 0.1
        return p.check(self.w, hp)

    def _presses(self):
        return [c.args[0] for c in self.w.key.call_args_list]

    def test_임계_이상이면_누르지_않는다(self):
        p = self._potion()
        self.assertEqual(p.check(self.w, 0.81), SKIP)
        self.w.key.assert_not_called()

    def test_임계_미만_2프레임이면_F6을_누른다(self):
        # 경계: 0.79 < 0.80 → 사용. 재판독 상승(0.95) → F6만 누른다.
        # F6 우선(2026-09-14 실측: F6=물약, F5=빈 슬롯).
        p = self._potion(lambda img: 0.95)
        self.assertEqual(self._armed(p, 0.79), USED)
        self.assertEqual(self._presses(), ["F5"])

    def test_한_프레임만의_저HP로는_누르지_않는다(self):
        # OCR 오독 한 프레임(0.79)이 F5를 발사하면 안 된다.
        p = self._potion()
        self.assertEqual(p.check(self.w, 0.79), SKIP)
        self.w.key.assert_not_called()
        # 다음 프레임 회복(0.95)이면 여전히 누르지 않는다.
        self.assertEqual(p.check(self.w, 0.95), SKIP)
        self.w.key.assert_not_called()

    def test_F6_무반응이면_F5로_폴백한다(self):
        # 재판독이 계속 낮으면(반응 없음) F6→F5 순서로 누른다.
        p = self._potion(lambda img: 0.79)
        self.assertEqual(self._armed(p, 0.79), USED)
        self.assertEqual(self._presses(), ["F5", "F6"])

    def test_쿨다운_중에는_재누름이_막힌다(self):
        p = self._potion(lambda img: 0.95)
        self.assertEqual(self._armed(p, 0.79), USED)
        before = self.w.key.call_count
        # 즉시 다시 저HP가 2프레임 연속 와도 COOLDOWN(3초) 내에는 안 누른다.
        self.assertEqual(p.check(self.w, 0.75), SKIP)  # 1프레임 기록
        p._low_since -= potion_keys.CONFIRM_GAP + 0.1
        self.assertEqual(p.check(self.w, 0.75), SKIP)  # 쿨다운 차단
        self.assertEqual(self.w.key.call_count, before)

    def test_hp_None이면_절대_누르지_않는다(self):
        p = self._potion()
        for _ in range(3):
            self.assertEqual(p.check(self.w, None), UNKNOWN)
        self.w.key.assert_not_called()

    def test_F5_F6_모두_무반응_3턴이면_재고_소진(self):
        p = self._potion(lambda img: 0.50)  # 재판독도 계속 낮음
        results = []
        for _ in range(3):
            results.append(self._armed(p, 0.50))
            p._last_used -= COOLDOWN + 0.1  # 쿨다운 해제(누적 관찰용)
        self.assertEqual(results, [USED, USED, EXHAUSTED])
        # 매턴 F5+F6 두 번씩: 3턴 × 2 = 6
        self.assertEqual(self.w.key.call_count, 6)


    def test_피가_딸리면_연속_투입한다(self):
        # 사용자 지시(2026-09-15): 피가 많이 딸리면 여러 번. 투입 후에도
        # 임계 밑이면 CHAIN_GAP 대기 후 재투입 — 임계 회복 시까지(상한 4회).
        reread = iter([0.60, 0.86])  # 1회차 +0.2, 2회차 후 임계 회복
        p = self._potion(lambda img: next(reread))
        self.assertEqual(self._armed(p, 0.40), USED)
        self.assertEqual(self._presses(), ["F5", "F5"])

    def test_연속_투입은_상한이_있다(self):
        # 재판독이 계속 소폭 상승(투입 효과)해도 임계 밑이면 이어가되
        # CHAIN_MAX(4회)까지만. 재판독이 멈추면(게임 쿨다운) 즉시 중단.
        reread = iter([0.55, 0.60, 0.65, 0.70, 0.75])
        p = self._potion(lambda img: next(reread))
        self.assertEqual(self._armed(p, 0.40), USED)
        self.assertEqual(len(self._presses()), 4)

    def test_F5_성공_후에는_F5를_먼저_누른다(self):
        # F6 무반응 → F5 반응: 다음 사용부터 F5 우선(학습).
        reread = iter([0.79, 0.95])  # F6 재판독 무반응, F5 재판독 상승
        p = self._potion(lambda img: next(reread))
        self.assertEqual(self._armed(p, 0.79), USED)
        self.assertEqual(self._presses(), ["F5", "F6"])
        self.assertEqual(p._first_key, "F5")

        p._last_used -= COOLDOWN + 0.1
        self.assertEqual(p.check(self.w, 0.70), SKIP)  # 1프레임 기록
        p._low_since -= potion_keys.CONFIRM_GAP + 0.1
        reread2 = iter([0.95])
        with patch.object(potion_keys, "hp_read", lambda img: next(reread2)):
            self.assertEqual(p.check(self.w, 0.70), USED)
        self.assertEqual(self._presses(), ["F6", "F5", "F5"])


if __name__ == "__main__":
    unittest.main()
