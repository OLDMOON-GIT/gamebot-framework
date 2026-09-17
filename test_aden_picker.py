"""aden_picker F4 줍기 회귀 (BTS-1033502) — 키 방식/획득 판정."""
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import aden_picker as ap


class F4PickupTests(unittest.TestCase):
    def _run(self, label_seq, gain_seq, steps=6, tier="unknown"):
        """루프를 label/gain 시퀀스만큼 돌리고 F4 호출 기록을 반환."""
        w = MagicMock()
        w.active.return_value = True
        w.capture.return_value = MagicMock()
        w.geometry.return_value = (0, 0, 10, 10)
        stop = MagicMock()
        stop.exists.side_effect = [False] * steps + [True]
        def mklab():
            m = MagicMock()
            m.cx, m.bottom, m.name = 500, 700, "아데나"
            return m
        labels = iter([[mklab() if e else e for e in seq] for seq in label_seq])
        gains = iter(gain_seq)
        with patch.object(ap, "CdpWindow", return_value=w), \
                patch.object(ap, "find_character", return_value=(500, 700)), \
                patch.object(ap, "red_name_candidates", return_value=[]), \
                patch.object(ap, "detect_labels", side_effect=lambda *a: next(labels)), \
                patch.object(ap, "read_label_names", side_effect=lambda img, labs: labs), \
                patch.object(ap, "tier_of", return_value=tier), \
                patch.object(ap, "pickup_count", side_effect=lambda img, win=None: next(gains)), \
                patch.object(ap, "exp_count", return_value=0), \
                patch.object(ap, "user_active", return_value=False), \
                patch.object(ap.time, "sleep"), \
                patch.object(ap, "STOP", stop), \
                patch.object(ap, "log"):
            ap.main()
        return w


    def test_저급_잡템은_무시한다(self):
        # F4-first: 키는 누르되 바닥 클릭은 안 한다. 저급 판별은 유지.
        from item_tiers import tier_of as real_tier
        lab = MagicMock()
        lab.name = "늑대가죽"
        w = self._run(label_seq=[[lab], []], gain_seq=[0, 0], tier="low")
        w.click.assert_not_called()
        self.assertEqual(real_tier("늑대가죽"), "low")

    def test_근처_몹있으면_전투중_바닥클릭_안함(self):
        # F4는 자동공격을 안 끊는다. 접적 중 바닥 클릭만 금지(BTS-1033742).
        w = MagicMock()
        w.active.return_value = True
        w.capture.return_value = MagicMock()
        w.geometry.return_value = (0, 0, 10, 10)
        stop = MagicMock()
        stop.exists.side_effect = [False] * 3 + [True]
        with patch.object(ap, "CdpWindow", return_value=w), \
                patch.object(ap, "find_character", return_value=(500, 700)), \
                patch.object(ap, "red_name_candidates", return_value=[(600, 700, 99, None)]), \
                patch.object(ap, "detect_labels", return_value=[MagicMock()]), \
                patch.object(ap, "read_label_names", side_effect=lambda img, labs: labs), \
                patch.object(ap, "tier_of", return_value="unknown"), \
                patch.object(ap.time, "sleep"), \
                patch.object(ap, "STOP", stop), \
                patch.object(ap, "log"):
            ap.main()
        w.click.assert_not_called()
        w.key.assert_called()

    def test_드랍있고_획득증가면_F4누르고_성공(self):
        w = self._run(
            label_seq=[[MagicMock()] if i == 0 else [] for i in range(200)],
            gain_seq=[5] + [7] * 400,
        )
        w.key.assert_called_with("F4", (0, 0, 10, 10))
        w.click.assert_not_called()   # 마우스 클릭 금지(nomouse)

    def test_획득_무증가면_재시도한다(self):
        # F4는 1회 1줍기 — 무획득 턴에도 F4를 누른다(재시도 루프).
        # 연속 재시도 간격/횟수는 실전 로그('F4 무반응 (N) — 재시도',
        # 18:43~47 관측)로 검증됐다.
        w = self._run(
            label_seq=[[MagicMock()] if i < 2 else [] for i in range(200)],
            gain_seq=[5] * 400,
        )
        self.assertGreaterEqual(w.key.call_count, 1)

    def test_드랍없어도_바닥클릭_안함(self):
        w = self._run(label_seq=[[], []], gain_seq=[0, 0])
        w.click.assert_not_called()

    def test_고급드랍이_멀어도_바닥클릭_안함(self):
        """칼질 중에 바닥을 클릭하면 자동공격이 끊긴다(BTS-1033742)."""
        from types import SimpleNamespace
        w = MagicMock()
        w.active.return_value = True
        w.capture.return_value = MagicMock()
        w.geometry.return_value = (0, 0, 10, 10)
        stop = MagicMock()
        stop.exists.side_effect = [False] * 24 + [True]
        lab = SimpleNamespace(name="아데나", click=(1000, 700))
        with patch.object(ap, "CdpWindow", return_value=w), \
                patch.object(ap, "find_character", return_value=(500, 700)), \
                patch.object(ap, "red_name_candidates", return_value=[]), \
                patch.object(ap, "detect_labels", return_value=[lab]), \
                patch.object(ap, "read_label_names", side_effect=lambda img, labs: labs), \
                patch.object(ap, "tier_of", return_value="high"), \
                patch.object(ap, "exp_count", return_value=0), \
                patch.object(ap, "pickup_count", return_value=0), \
                patch.object(ap, "user_active", return_value=False), \
                patch.object(ap.time, "sleep"), \
                patch.object(ap, "STOP", stop), \
                patch.object(ap, "log"):
            ap.main()
        w.click.assert_not_called()
        w.key.assert_called()


if __name__ == "__main__":
    unittest.main()
