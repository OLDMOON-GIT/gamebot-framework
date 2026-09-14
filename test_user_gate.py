"""사용자 양보 게이트 검증 — 움직임 감지와 정지 판정."""
import os
import unittest
from unittest.mock import patch, MagicMock

import user_gate


def _gate_enabled():
    """게이트 테스트는 스킵 플래그를 끄고 실동작을 검증한다."""
    saved = os.environ.pop("LINC_SKIP_USER_GATE", None)
    def restore():
        if saved is not None:
            os.environ["LINC_SKIP_USER_GATE"] = saved
    return restore


class GateTests(unittest.TestCase):
    def test_movement_detected(self):
        """포인터가 움직이면 사용자 활동으로 판정한다."""
        restore = _gate_enabled()
        self.addCleanup(restore)
        fake = MagicMock()
        seq = [((10, 10), 1), ((12, 10), 1)]  # x 이동
        states = iter(seq)
        with patch.object(user_gate.time, "sleep"), \
                patch.object(user_gate, "display") as df, \
                patch.object(user_gate.time, "monotonic",
                             side_effect=[0, 0.1, 99]):
            d = df.Display.return_value
            d.screen.return_value.root.query_pointer.side_effect = [
                MagicMock(root_x=s[0][0], root_y=s[0][1]) for s in seq]
            d.intern_atom.return_value = 1
            prop = MagicMock(); prop.value = [1]
            d.screen.return_value.root.get_full_property.return_value = prop
            self.assertTrue(user_gate.user_active(observe=1, poll=0.1))

    def test_stillness_not_active(self):
        """포인터/활성창 정지면 사용자 활동 아니다(봇 터치 허용)."""
        restore = _gate_enabled()
        self.addCleanup(restore)
        with patch.object(user_gate.time, "sleep"), \
                patch.object(user_gate, "display") as df, \
                patch.object(user_gate.time, "monotonic",
                             side_effect=[0, 0.1, 0.2, 0.3, 99]):
            d = df.Display.return_value
            d.screen.return_value.root.query_pointer.side_effect = [
                MagicMock(root_x=5, root_y=5) for _ in range(10)]
            d.intern_atom.return_value = 1
            prop = MagicMock(); prop.value = [7]
            d.screen.return_value.root.get_full_property.return_value = prop
            self.assertFalse(user_gate.user_active(observe=1, poll=0.1))

    def test_keyboard_only_detected(self):
        """포인터/활성창은 그대로여도 키가 눌려 있으면 사용자 활동(키보드 사각 해소)."""
        restore = _gate_enabled()
        self.addCleanup(restore)
        with patch.object(user_gate.time, "sleep"), \
                patch.object(user_gate, "display") as df, \
                patch.object(user_gate.time, "monotonic",
                             side_effect=[0, 0.1, 99]):
            d = df.Display.return_value
            d.screen.return_value.root.query_pointer.side_effect = [
                MagicMock(root_x=5, root_y=5) for _ in range(10)]
            d.intern_atom.return_value = 1
            prop = MagicMock(); prop.value = [7]
            d.screen.return_value.root.get_full_property.return_value = prop
            d.query_keymap.return_value = [0] * 10 + [0x10] + [0] * 21
            self.assertTrue(user_gate.user_active(observe=1, poll=0.1))

    def test_no_keys_still_not_active(self):
        """키맵이 전부 0이면(키 안 눌림) 정지 판정 유지."""
        restore = _gate_enabled()
        self.addCleanup(restore)
        with patch.object(user_gate.time, "sleep"), \
                patch.object(user_gate, "display") as df, \
                patch.object(user_gate.time, "monotonic",
                             side_effect=[0, 0.1, 0.2, 99]):
            d = df.Display.return_value
            d.screen.return_value.root.query_pointer.side_effect = [
                MagicMock(root_x=5, root_y=5) for _ in range(10)]
            d.intern_atom.return_value = 1
            prop = MagicMock(); prop.value = [7]
            d.screen.return_value.root.get_full_property.return_value = prop
            d.query_keymap.return_value = [0] * 32
            self.assertFalse(user_gate.user_active(observe=1, poll=0.1))


if __name__ == "__main__":
    unittest.main()
