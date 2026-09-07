"""상태에 따른 입력 차단과 X11 좌표 검증."""

import unittest
from unittest.mock import Mock, patch

from linux_bot import choose_action, choose_move_or_potion, input_unchanged
from linux_window import PurpleWindow


class DecisionTests(unittest.TestCase):
    def state(self, **changes):
        result = dict(ready=True, hp=1.0, safe_zone=False, mobs=[(800, 400, 100)])
        result.update(changes)
        return result

    def test_probe_never_sends(self):
        self.assertIsNone(choose_action(self.state(), running=False))

    def test_unreadable_dead_or_safe_zone_never_attacks(self):
        for changes in [dict(ready=False), dict(hp=None), dict(hp=0), dict(safe_zone=True)]:
            with self.subTest(changes=changes):
                self.assertIsNone(choose_action(self.state(**changes), running=True))

    def test_low_hp_without_verified_key_stops_attack(self):
        self.assertIsNone(choose_action(self.state(hp=.3), running=True))

    def test_potion_has_priority_over_combat(self):
        self.assertEqual(choose_action(self.state(hp=.3), running=True, potion_key="F5"),
                         ("물약", "F5"))

    def test_move_mode_takes_potion_first_when_low_hp(self):
        self.assertEqual(choose_move_or_potion(self.state(hp=.3), (580, 700), "F1"),
                         ("물약", "F1"))
        self.assertEqual(choose_move_or_potion(self.state(hp=.3), (580, 700)), ("이동", (580, 700)))

    def test_move_mode_moves_on_full_or_unreadable_hp(self):
        self.assertEqual(choose_move_or_potion(self.state(), (580, 700), "F1"), ("이동", (580, 700)))
        self.assertEqual(choose_move_or_potion(self.state(hp=None), (580, 700), "F1"),
                         ("이동", (580, 700)))
        self.assertEqual(choose_move_or_potion(self.state(hp=0), (580, 700), "F1"),
                         ("이동", (580, 700)))

    def test_verified_mob_can_be_clicked(self):
        self.assertEqual(choose_action(self.state(), running=True), ("공격", (800, 400)))

    def test_pointer_change_during_ocr_blocks_input(self):
        window, stop = Mock(), Mock()
        window.stop_pressed.return_value = False
        stop.exists.return_value = False
        window.pointer.return_value = (99, 99)
        self.assertFalse(input_unchanged(window, (10, 10), stop))
        window.pointer.return_value = (10, 10)
        self.assertTrue(input_unchanged(window, (10, 10), stop))
        stop.exists.return_value = True
        self.assertFalse(input_unchanged(window, (10, 10), stop))


class WindowTests(unittest.TestCase):
    def test_short_f12_press_is_latched(self):
        from Xlib import X
        obj = self.stub()
        obj.stop_keycode = 96
        obj.stop_latched = False
        obj.connection.pending_events.side_effect = [1, 0, 0]
        obj.connection.next_event.return_value = Mock(type=X.KeyPress, detail=96)
        self.assertTrue(obj.stop_pressed())
        self.assertTrue(obj.stop_pressed())

    def stub(self):
        obj = PurpleWindow.__new__(PurpleWindow)
        obj.active = Mock(return_value=True)
        obj.geometry = Mock(return_value=(1802, 173, 1933, 1332))
        obj.connection = Mock()
        obj.window_id = 0x123
        obj.root = Mock()
        obj.root.get_full_property.return_value = None
        point = Mock()
        point.root_x, point.root_y = 10, 10
        obj.root.query_pointer.return_value = point
        obj.pointer = Mock(return_value=(10, 10))
        return obj

    @patch("linux_window.xtest.fake_input")
    def test_inactive_window_cannot_receive_input(self, send):
        obj = self.stub()
        obj.active.return_value = False
        with self.assertRaises(RuntimeError):
            obj.click(800, 500, obj.geometry())
        send.assert_not_called()

    @patch("linux_window.xtest.fake_input")
    def test_moved_window_cannot_receive_input(self, send):
        obj = self.stub()
        with self.assertRaises(RuntimeError):
            obj.click(800, 500, (0, 0, 1933, 1332))
        send.assert_not_called()

    @patch("linux_window.xtest.fake_input")
    def test_sidebar_and_hud_cannot_receive_clicks(self, send):
        obj = self.stub()
        for pos in [(200, 500), (1000, 1100), (1000, 75), (1920, 500)]:
            with self.subTest(pos=pos), self.assertRaises(ValueError):
                obj.click(*pos, obj.geometry())
        send.assert_not_called()

    @patch("linux_window.xtest.fake_input")
    def test_focus_change_after_pointer_move_cancels_button(self, send):
        obj = self.stub()
        obj.active.side_effect = [True, False]
        with self.assertRaises(RuntimeError):
            obj.click(800, 500, obj.geometry())
        self.assertEqual(send.call_count, 1)


if __name__ == "__main__":
    unittest.main()
