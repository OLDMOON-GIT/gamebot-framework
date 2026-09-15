"""aden_picker F4 줍기 회귀 (BTS-1033502) — 키 방식/획득 판정."""
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import aden_picker as ap


class F4PickupTests(unittest.TestCase):
    def _run(self, label_seq, gain_seq, steps=6):
        """루프를 label/gain 시퀀스만큼 돌리고 F4 호출 기록을 반환."""
        w = MagicMock()
        w.active.return_value = True
        w.capture.return_value = MagicMock()
        w.geometry.return_value = (0, 0, 10, 10)
        potion = MagicMock()
        potion.check.return_value = None
        stop = MagicMock()
        stop.exists.side_effect = [False] * steps + [True]
        labels = iter(label_seq)
        gains = iter(gain_seq)
        with patch.object(ap, "CdpWindow", return_value=w), \
                patch.object(ap, "PotionKeys", return_value=potion), \
                patch.object(ap, "hp_read", return_value=0.95), \
                patch.object(ap, "find_character", return_value=(500, 700)), \
                patch.object(ap, "red_name_candidates", return_value=[]), \
                patch.object(ap, "detect_labels", side_effect=lambda *a: next(labels)), \
                patch.object(ap, "pickup_count", side_effect=lambda img: next(gains)), \
                patch.object(ap, "user_active", return_value=False), \
                patch.object(ap.time, "sleep"), \
                patch.object(ap, "STOP", stop), \
                patch.object(ap, "log"):
            ap.main()
        return w

    def test_근처_몹있으면_전투중_줍기_보류(self):
        # 사용자 지시: 몬스터 사냥 중이 아니라 사냥 없을 때 주워라.
        # 캐릭터 (500,700) 반경 260px 안에 몹 (600,700) → 접적: F4 안 누름.
        w = MagicMock()
        w.active.return_value = True
        w.capture.return_value = MagicMock()
        stop = MagicMock()
        stop.exists.side_effect = [False] * 3 + [True]
        with patch.object(ap, "CdpWindow", return_value=w), \
                patch.object(ap, "PotionKeys", return_value=MagicMock(check=MagicMock(return_value=None))), \
                patch.object(ap, "hp_read", return_value=0.95), \
                patch.object(ap, "find_character", return_value=(500, 700)), \
                patch.object(ap, "red_name_candidates", return_value=[(600, 700, 99, None)]), \
                patch.object(ap, "detect_labels", return_value=[MagicMock()]), \
                patch.object(ap.time, "sleep"), \
                patch.object(ap, "STOP", stop), \
                patch.object(ap, "log"):
            ap.main()
        w.key.assert_not_called()

    def test_드랍있고_획득증가면_F4누르고_성공(self):
        w = self._run(
            label_seq=[[MagicMock()], []],
            gain_seq=[5, 7],   # F4 전 5, 후 7 → 획득 +2
        )
        w.key.assert_called_once_with("F4", (0, 0, 10, 10))
        w.click.assert_not_called()   # 마우스 클릭 금지(nomouse)

    def test_획득_무증가면_무반응_재시도(self):
        w = self._run(
            label_seq=[[MagicMock()], [MagicMock()], []],
            gain_seq=[5, 5, 5, 5],    # 두 번 시도 모두 증가 없음
        )
        self.assertEqual(w.key.call_count, 2)

    def test_드랍없으면_F4_안누름(self):
        w = self._run(label_seq=[[], []], gain_seq=[0, 0])
        w.key.assert_not_called()


if __name__ == "__main__":
    unittest.main()
