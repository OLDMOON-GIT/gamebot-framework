"""열려 있는 퍼플온 X11 창 캡처와 활성 창에 한정한 입력."""

import subprocess
import time

import numpy as np
from PIL import ImageGrab
from Xlib import X, XK, display
from Xlib.ext import xtest


CALIBRATED_GEOMETRY = (1457, 468, 1933, 1332)


class PurpleWindow:
    def __init__(self, window_id=None):
        self.connection = display.Display()
        self.root = self.connection.screen().root
        if window_id is None:
            listing = self.root.get_full_property(
                self.connection.intern_atom("_NET_CLIENT_LIST"), X.AnyPropertyType)
            candidates = []
            for ident in listing.value if listing is not None else []:
                win = self.connection.create_resource_object("window", int(ident))
                title = self._title(win)
                if title == "PURPLE On - Chromium":
                    candidates.append(int(ident))
            if len(candidates) != 1:
                raise RuntimeError(f"퍼플온 창을 하나로 특정할 수 없습니다: {len(candidates)}개")
            window_id = candidates[0]
        self.window = self.connection.create_resource_object("window", window_id)
        self.window_id = window_id
        self.window_size_hint = (CALIBRATED_GEOMETRY[2], CALIBRATED_GEOMETRY[3])
        self.stop_keycode = self.connection.keysym_to_keycode(XK.string_to_keysym("F12"))
        self.stop_latched = False
        self.root.grab_key(self.stop_keycode, X.AnyModifier, False,
                           X.GrabModeAsync, X.GrabModeAsync)
        self.connection.sync()

    def find_and_restore(self):
        """퍼플온 창이 재생성/리사이즈됐을 때 다시 찾아 캘리브레이션 위치로 복구한다.

        웹플레이 스트리밍 세션 전환으로 창 ID가 바뀌는 경우(2026-09-07 실측
        3회) 사냥이 화면 크기 불일치로 멈춘다. 창을 다시 특정해 크기/위치를
        복원하고 활성화한다. 실패 시 예외를 던지고 호출자가 대기한다.
        """
        listing = self.root.get_full_property(
            self.connection.intern_atom("_NET_CLIENT_LIST"), X.AnyPropertyType)
        found = [int(ident) for ident in (listing.value if listing is not None else [])
                 if self._title(self.connection.create_resource_object("window", int(ident)))
                 == "PURPLE On - Chromium"]
        if len(found) != 1:
            raise RuntimeError(f"퍼플온 창을 하나로 특정할 수 없습니다: {len(found)}개")
        if found[0] != self.window_id:
            self.window = self.connection.create_resource_object("window", found[0])
            self.window_id = found[0]
        geometry = self.window.get_geometry()
        if (geometry.width, geometry.height) != (CALIBRATED_GEOMETRY[2], CALIBRATED_GEOMETRY[3]):
            subprocess.run(
                ["wmctrl", "-i", "-r", str(self.window_id), "-e",
                 "0,%d,%d,%d,%d" % CALIBRATED_GEOMETRY],
                check=True, timeout=5)
            self.connection.sync()
        # 포커스를 뺏지 않는다: 최소화만 해제하고 '항상 위'로 고정한다.
        subprocess.run(["wmctrl", "-i", "-r", str(self.window_id), "-b",
                        "remove,hidden,shaded"], check=True, timeout=5)
        subprocess.run(["wmctrl", "-i", "-r", str(self.window_id), "-b",
                        "add,above"], check=True, timeout=5)
        self.connection.sync()
        return self.geometry()

    def _title(self, win):
        prop = win.get_full_property(
            self.connection.intern_atom("_NET_WM_NAME"), X.AnyPropertyType)
        if prop is not None:
            return (prop.value if isinstance(prop.value, str)
                    else bytes(prop.value).decode("utf-8", errors="replace"))
        return win.get_wm_name() or ""

    def geometry(self):
        geometry = self.window.get_geometry()
        position = self.root.translate_coords(self.window, 0, 0)
        return position.x, position.y, geometry.width, geometry.height

    def active(self):
        """활성 포커스 대신 창이 화면에 표시되는지만 확인한다.

        포커스 강제(wmctrl -a)가 사용자 작업을 방해하므로(2026-09-07 요청)
        창은 '항상 위'로 유지하고 포커스와 무관하게 동작시킨다.
        """
        try:
            geometry = self.window.get_geometry()
            attrs = self.window.get_attributes()
            return (geometry.width, geometry.height) == self.window_size_hint \
                and attrs.map_state == X.IsViewable
        except Exception:
            return False

    def capture(self):
        """화면에 보이는 픽셀을 캡처하므로 다른 창이 가리면 그대로 나타난다."""
        x, y, width, height = self.geometry()
        screen = self.root.get_geometry()
        if x < 0 or y < 0 or x + width > screen.width or y + height > screen.height:
            raise RuntimeError("퍼플온 창 일부가 화면 밖에 있습니다")
        raw = ImageGrab.grab(bbox=(x, y, x + width, y + height),
                             xdisplay=self.connection.get_display_name())
        return np.asarray(raw.convert("RGB"))[:, :, ::-1].copy()

    def pointer(self):
        point = self.root.query_pointer()
        return point.root_x, point.root_y

    def stop_pressed(self):
        # OCR 처리 중 눌렀다 떼더라도 X11 큐의 키 누름 이벤트를 보존한다.
        while self.connection.pending_events():
            event = self.connection.next_event()
            if event.type == X.KeyPress and event.detail == self.stop_keycode:
                self.stop_latched = True
        return self.stop_latched

    def _focused_window(self):
        prop = self.root.get_full_property(
            self.connection.intern_atom("_NET_ACTIVE_WINDOW"), X.AnyPropertyType)
        return int(prop.value[0]) if prop is not None and len(prop.value) else None

    def _restore_focus(self, focused, pointer):
        """입력 직후 사용자의 포커스와 마우스 커서를 원래대로 돌려놓는다."""
        point = self.root.query_pointer()
        if focused and focused != self.window_id:
            try:
                subprocess.run(["wmctrl", "-i", "-a", str(focused)],
                               check=True, timeout=3)
            except (OSError, subprocess.SubprocessError):
                pass
        if pointer and (point.root_x, point.root_y) != pointer:
            xtest.fake_input(self.connection, X.MotionNotify,
                             x=pointer[0], y=pointer[1])
            self.connection.sync()

    def click(self, x, y, expected_geometry, hover=0.0):
        """호출자가 판독한 프레임과 창 위치가 같을 때만 입력한다.

        hover>0이면 몬스터처럼 커서 인식이 필요한 대상을 위해 마우스를
        해당 위치에 잠시 머물게 한다. 실측(2026-09-07): hover 0.7초 이상이어야
        몹 클릭이 이동이 아닌 공격으로 해석된다.
        """
        if not self.active() or self.geometry() != expected_geometry:
            raise RuntimeError("입력 직전 창 활성 상태 또는 위치가 변경됐습니다")
        left, top, width, height = expected_geometry
        if not (500 < x < width - 45 and 220 < y < 960):
            raise ValueError("클릭 위치가 검증된 플레이 영역 밖입니다")
        focused = self._focused_window()
        pointer = self.pointer()
        xtest.fake_input(self.connection, X.MotionNotify, x=left + x, y=top + y)
        self.connection.sync()
        if hover:
            time.sleep(hover)
        # 이동 직후 창 상태도 다시 확인한다. 창 포커스는 강제로 바꾸지 않는다.
        if not self.active() or self.geometry() != expected_geometry:
            raise RuntimeError("마우스 이동 후 대상 창이 변경됐습니다")
        try:
            xtest.fake_input(self.connection, X.ButtonPress, 1)
            try:
                self.connection.sync()
                time.sleep(0.12)
            finally:
                xtest.fake_input(self.connection, X.ButtonRelease, 1)
                self.connection.sync()
        finally:
            self._restore_focus(focused, pointer)

    def key(self, name, expected_geometry):
        if name not in {f"F{i}" for i in range(1, 9)}:
            raise ValueError("물약 키는 확인된 F1~F8만 사용할 수 있습니다")
        if not self.active() or self.geometry() != expected_geometry:
            raise RuntimeError("키 입력 직전 대상 창이 변경됐습니다")
        keycode = self.connection.keysym_to_keycode(XK.string_to_keysym(name))
        focused = self._focused_window()
        pointer = self.pointer()
        try:
            # 키보드 이벤트는 활성 창으로 가므로 입력 동안만 포커스를 빌린다.
            if focused != self.window_id:
                subprocess.run(["wmctrl", "-i", "-a", str(self.window_id)],
                               check=True, timeout=3)
                time.sleep(0.15)
            xtest.fake_input(self.connection, X.KeyPress, keycode)
            try:
                self.connection.sync()
            finally:
                xtest.fake_input(self.connection, X.KeyRelease, keycode)
                self.connection.sync()
        finally:
            self._restore_focus(focused, pointer)

    def close(self):
        self.root.ungrab_key(self.stop_keycode, X.AnyModifier)
        self.connection.close()
