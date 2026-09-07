"""사용자 화면과 분리된 Xvfb에서 실제 X11 캡처와 입력 차단을 검증한다."""

import os
import select
import shutil
import subprocess
import unittest
from unittest.mock import patch

import numpy as np
from Xlib import X, XK, display
from Xlib.ext import xtest

from linux_window import PurpleWindow


@unittest.skipUnless(shutil.which("Xvfb"), "Xvfb가 설치되지 않았습니다")
class X11IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = subprocess.Popen(
            ["Xvfb", "-displayfd", "1", "-screen", "0", "2000x1400x24",
             "-nolisten", "tcp"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        cls.addClassCleanup(cls.stop_test_server)
        readable, _, _ = select.select([cls.server.stdout], [], [], 5)
        if not readable:
            raise RuntimeError("테스트 전용 Xvfb 시작 시간이 초과됐습니다")
        number = cls.server.stdout.readline().strip()
        if not number.isdigit():
            raise RuntimeError("테스트 전용 Xvfb가 화면 번호를 반환하지 않았습니다")
        cls.test_display = ":" + number
        # 자동 할당된 독립 서버만 연결하며 기존 사용자 화면은 사용하지 않는다.
        if cls.test_display == ":0" or cls.test_display == os.environ.get("DISPLAY"):
            raise RuntimeError("테스트 화면이 사용자 화면과 분리되지 않았습니다")

    @classmethod
    def stop_test_server(cls):
        # 직접 생성한 테스트 서버만 종료한다.
        if cls.server.poll() is None:
            cls.server.terminate()
            try:
                cls.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.server.kill()
                cls.server.wait(timeout=5)
        cls.server.stdout.close()
        cls.server.stderr.close()

    def setUp(self):
        environment = patch.dict(os.environ, {"DISPLAY": self.test_display})
        environment.start()
        self.addCleanup(environment.stop)
        self.observer = display.Display(self.test_display)
        self.addCleanup(self.observer.close)
        self.root = self.observer.screen().root
        self.target = self.root.create_window(
            20, 30, 1933, 1332, 0, self.observer.screen().root_depth,
            X.InputOutput, X.CopyFromParent, background_pixel=0x123456,
            event_mask=X.KeyPressMask | X.KeyReleaseMask |
            X.ButtonPressMask | X.ButtonReleaseMask | X.PointerMotionMask)
        self.target.change_property(
            self.atom("_NET_WM_NAME"), self.atom("UTF8_STRING"), 8,
            "PURPLE On - Chromium".encode("utf-8"))
        self.root.change_property(
            self.atom("_NET_CLIENT_LIST"), self.atom("WINDOW"), 32, [self.target.id])
        self.set_active(self.target.id)
        self.target.map()
        self.target.set_input_focus(X.RevertToParent, X.CurrentTime)
        self.observer.sync()
        self.window = PurpleWindow()
        self.addCleanup(self.window.close)

    def atom(self, name):
        return self.observer.intern_atom(name)

    def set_active(self, window_id):
        self.root.change_property(
            self.atom("_NET_ACTIVE_WINDOW"), self.atom("WINDOW"), 32, [window_id])
        self.observer.sync()

    def drain_events(self):
        self.observer.sync()
        events = []
        while self.observer.pending_events():
            events.append(self.observer.next_event())
        return events

    def test_real_capture_geometry_and_active_window(self):
        self.assertEqual(self.window.window_id, self.target.id)
        self.assertEqual(self.window.geometry(), (20, 30, 1933, 1332))
        self.assertTrue(self.window.active())
        frame = self.window.capture()
        self.assertEqual(frame.shape, (1332, 1933, 3))
        np.testing.assert_array_equal(frame[100, 100], [0x56, 0x34, 0x12])

    def test_real_window_move_updates_absolute_coordinates(self):
        self.target.configure(x=40, y=50)
        self.observer.sync()
        self.assertEqual(self.window.geometry(), (40, 50, 1933, 1332))
        np.testing.assert_array_equal(self.window.capture()[100, 100], [0x56, 0x34, 0x12])

    def test_changed_tab_title_no_longer_blocks_under_size_policy(self):
        """포커스 강제 폐지(2026-09-07) 이후 제목이 아니라 크기로 판정한다."""
        self.target.change_property(
            self.atom("_NET_WM_NAME"), self.atom("UTF8_STRING"), 8,
            "다른 탭 - Chromium".encode("utf-8"))
        self.observer.sync()
        self.assertTrue(self.window.active())

    def test_wrong_window_size_blocks_active_detection(self):
        self.target.configure(width=1600, height=900)
        self.observer.sync()
        self.assertFalse(self.window.active())

    def test_short_real_f12_press_remains_latched_after_release(self):
        self.assertFalse(self.window.stop_pressed())
        code = self.observer.keysym_to_keycode(XK.string_to_keysym("F12"))
        xtest.fake_input(self.observer, X.KeyPress, code)
        xtest.fake_input(self.observer, X.KeyRelease, code)
        self.observer.sync()
        self.window.connection.sync()
        # 키를 이미 뗀 상태여도 큐에 보존된 중지 요청을 읽어야 한다.
        keys = self.observer.query_keymap()
        self.assertFalse(keys[code // 8] & (1 << (code % 8)))
        self.assertTrue(self.window.stop_pressed())
        self.assertTrue(self.window.stop_pressed())

    def test_inactive_focus_window_allows_click_under_size_policy(self):
        """포커스가 없어도 크기·표시 정책이면 클릭을 허용한다(사용자 포커스 보호)."""
        self.set_active(self.root.id)
        self.assertTrue(self.window.active())
        self.drain_events()
        self.window.click(800, 500, self.window.geometry())
        events = self.drain_events()
        self.assertTrue(any(e.type in (X.ButtonPress, X.ButtonRelease) for e in events))
        # 창 위치가 판독과 달라지면 여전히 거부한다.
        self.target.configure(x=999)
        self.observer.sync()
        with self.assertRaises(RuntimeError):
            self.window.click(800, 500, (40, 50, 1933, 1332))


if __name__ == "__main__":
    unittest.main()
