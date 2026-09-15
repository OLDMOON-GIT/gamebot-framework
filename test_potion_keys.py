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
from potion_keys import COOLDOWN, EXHAUSTED, SKIP, UNKNOWN, USED, PotionKeys


class TestPotionKeys(unittest.TestCase):
    def setUp(self):
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
        self.assertEqual(self._presses(), ["F6"])

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
        self.assertEqual(self._presses(), ["F6", "F5"])

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

    def test_F5_F6_모두_무반응_3턴이면_F8_귀환(self):
        p = self._potion(lambda img: 0.50)  # 재판독도 계속 낮음
        results = []
        for _ in range(3):
            results.append(self._armed(p, 0.50))
            p._last_used -= COOLDOWN + 0.1  # 쿨다운 해제(누적 관찰용)
        # 사용자 지시: 소진 시 F8(귀환 주문서) — EXHAUSTED 대신 RETURN.
        self.assertEqual(results, [USED, USED, potion_keys.RETURN])
        # 매턴 F6+F5 두 번씩 3턴(6회) + 마지막 F8 1회 = 7
        self.assertEqual(self.w.key.call_count, 7)

    def test_HP_20퍼미만이면_즉시_F8_귀환(self):
        # 사용자 지시: '물약이 아예없거나 20퍼미만의 경우 f8'.
        p = self._potion(lambda img: 0.95)
        r = self._armed(p, 0.15)
        self.assertEqual(r, potion_keys.RETURN)
        presses = [c.args[0] for c in self.w.key.call_args_list]
        self.assertIn("F8", presses)


    def test_피가_딸리면_연속_투입한다(self):
        # 사용자 지시(2026-09-15): 피가 많이 딸리면 여러 번. 투입 후에도
        # 임계 밑이면 CHAIN_GAP 대기 후 재투입 — 임계 회복 시까지(상한 4회).
        reread = iter([0.60, 0.86])  # 1회차 +0.2, 2회차 후 임계 회복
        p = self._potion(lambda img: next(reread))
        self.assertEqual(self._armed(p, 0.40), USED)
        self.assertEqual(self._presses(), ["F6", "F6"])

    def test_연속_투입은_상한이_있다(self):
        # 재판독이 계속 소폭 상승(투입 효과)해도 임계 밑이면 이어가되
        # CHAIN_MAX(4회)까지만. 재판독이 멈추면(게임 쿨다운) 즉시 중단.
        reread = iter([0.55, 0.60, 0.65, 0.70, 0.75, 0.78, 0.80, 0.80])
        p = self._potion(lambda img: next(reread))
        self.assertEqual(self._armed(p, 0.40), USED)
        # 시작 0.40은 위기(사용자 지시 '40퍼 쭉쭉 내려가면 80 이상')라
        # 상한 CHAIN_MAX+2=6회까지 이어간다.
        self.assertEqual(len(self._presses()), 6)


    def test_급감하면_임계가_상향된다(self):
        # 사용자 지시(2026-09-15): '피가 줄어드는 속도에 따라 빨아야됨'.
        # 초당 ~7%p씩 떨어지는 관측이 쌓이면 임계가 0.80+α로 올라가
        # 0.85 같은 값에서도 즉시 투입한다.
        p = self._potion(lambda img: 0.95)
        import time as _t
        # 관측 히스토리: 1초에 걸쳐 0.90→0.83(≈0.07/s 하락) → 임계 상향.
        p._hp_hist = [(_t.monotonic() - 1.0, 0.92), (_t.monotonic(), 0.82)]  # ~0.10/s
        self.assertEqual(self._armed(p, 0.85), USED)

    def test_안정이면_기본_임계_유지(self):
        p = self._potion(lambda img: 0.95)
        p.check(self.w, 0.82)
        p.check(self.w, 0.82)  # 하락 없음 → rate None → 기본 0.80
        # 0.81은 기본 임계 위라 누르지 않는다
        self.assertEqual(p.check(self.w, 0.81), SKIP)

    def test_설정_키_우선_고정_무반응시_보조_폴백(self):
        # 확장 UI 설정(BTS): potion_key가 매 턴 고정된다(학습 리셋 제거).
        # F6(설정) 무반응 → F5(보조) 반응. 다음 턴에도 설정 키 F6 우선.
        reread = iter([0.79, 0.95])  # F6 재판독 무반응, F5 재판독 상승
        p = self._potion(lambda img: next(reread))
        self.assertEqual(self._armed(p, 0.79), USED)
        self.assertEqual(self._presses(), ["F6", "F5"])
        self.assertEqual(p._first_key, "F6")  # 설정 키 유지


if __name__ == "__main__":
    unittest.main()
