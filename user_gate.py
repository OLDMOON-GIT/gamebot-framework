"""사용자 입력 양보 게이트 — 사용자가 마우스를 쓰고 있으면 봇이 터치를 쉰다.

CDP 터치는 X 포인터를 움직이지 않는다. 따라서 포인터가 움직이거나 활성
창이 바뀌면 그건 실제 사용자 입력이고, 봇 터치(=봇 크롬 activate → 포커스
탈취)와 충돌한다. 봇은 사용자가 조작 중이면 기다렸다가 손을 뗀 뒤에만
움직인다(2026-09-09 사용자 지적 '또 마우스'의 구조적 해결).
"""

import os
import time

from Xlib import X, display

_OBSERVE_SECONDS = 2.0
_POLL = 0.25


def _pointer_state(dpy, root):
    pointer = root.query_pointer()
    return pointer.root_x, pointer.root_y


def _active_window(dpy, root):
    prop = root.get_full_property(dpy.intern_atom("_NET_ACTIVE_WINDOW"),
                                  X.AnyPropertyType)
    return int(prop.value[0]) if prop and prop.value else 0


def user_active(observe=_OBSERVE_SECONDS, poll=_POLL):
    """관찰 구간 동안 사용자 입력(포인터 이동/활성창 전환)이 있으면 True."""
    if os.environ.get("LINC_SKIP_USER_GATE") == "1":
        return False  # 테스트/긴급 수동 스위치
    try:
        dpy = display.Display()
    except Exception:
        return False  # X 자체를 못 쓰면 판정 불가 — 봇은 동작하게 둔다
    try:
        root = dpy.screen().root
        start = (_pointer_state(dpy, root), _active_window(dpy, root))
        deadline = time.monotonic() + observe
        while time.monotonic() < deadline:
            time.sleep(poll)
            now = (_pointer_state(dpy, root), _active_window(dpy, root))
            if now != start:
                return True
        return False
    finally:
        dpy.close()
