"""CDP(원격 디버깅) 기반 퍼플온 제어 — 창 포커스/가림과 무관한 캡처+입력.

2026-09-07 설계 전환: X11 실좌표 입력은 몹 클릭 순간 마우스·포커스를
뺏는다(사용자 지적). 크로미움 DevTools 프로토콜로 브라우저에 직접
이벤트를 전달하면 창이 뒤에 있어도 조작되고 마우스 커서도 움직이지
않는다. 사냥 전용 크롬(--remote-debugging-port=9333, 전용 프로필) 대상.
"""

import base64
import json
import time
import urllib.request

import cv2
import numpy as np
import websocket

from linux_vision import WINDOW_SIZE


CDP_PORT = 9333
# 캘리브레이션과 동일한 뷰포트를 강제해 X11 판독 좌표계를 그대로 쓴다.
VIEWPORT = {"width": WINDOW_SIZE[0], "height": WINDOW_SIZE[1],
            "deviceScaleFactor": 1, "mobile": False}
F_KEYCODES = {f"F{i}": 111 + i for i in range(1, 13)}  # F1=112 ... windowsVirtualKeyCode

# 게임 스트림 좌표계(2026-09-07 실측): 비디오 rect (401,102) 1531x1148에
# 1280x960 스트림이 확대 렌더링된다. 스크린샷 좌표 → 게임 좌표 변환 후
# dispatch해야 서버가 정확한 지점을 클릭한다(미변환 클릭은 엉뚱한 이동).
VIDEO_RECT = (401, 102, 1531, 1148)
STREAM_SIZE = (1280, 960)


def to_stream(x, y):
    """스크린샷(뷰포트) 좌표를 게임 스트림 좌표로 변환한다."""
    vx, vy, vw, vh = VIDEO_RECT
    sw, sh = STREAM_SIZE
    return round((x - vx) * sw / vw), round((y - vy) * sh / vh)


class CdpWindow:
    """linux_window.PurpleWindow와 같은 인터페이스의 CDP 백엔드."""

    def __init__(self, port=CDP_PORT, url_prefix="purpleon"):
        tabs = json.load(urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json", timeout=5))
        pages = [t for t in tabs if t.get("type") == "page"
                 and url_prefix in t.get("url", "")]
        if len(pages) != 1:
            raise RuntimeError(f"퍼플온 탭을 하나로 특정할 수 없습니다: {len(pages)}개")
        self.ws = websocket.create_connection(
            pages[0]["webSocketDebuggerUrl"], timeout=20, suppress_origin=True)
        self.msg_id = 0
        self.window_id = 0  # 인터페이스 호환용
        self._cap_size = WINDOW_SIZE  # 최근 캡처 크기(클릭 역스케일용)
        # 2026-09-09: Emulation.setDeviceMetricsOverride(VIEWPORT)를 제거했다.
        # 오버라이드는 연결 시마다 사용자가 키운 창을 1933x1332로 되돌렸다
        # (사용자 지적). 대신 캡처를 WINDOW_SIZE로 정규화하고 클릭 좌표를
        # 실제 뷰포트로 역스케일해 창 크기와 무관하게 동작한다.

    def send(self, method, params=None):
        self.msg_id += 1
        self.ws.send(json.dumps({"id": self.msg_id, "method": method,
                                 "params": params or {}}))
        while True:
            resp = json.loads(self.ws.recv())
            if resp.get("id") == self.msg_id:
                if "error" in resp:
                    raise RuntimeError(f"CDP {method} 오류: {resp['error']}")
                return resp.get("result", {})

    # --- PurpleWindow 호환 인터페이스 ---
    def active(self):
        """게임 스트리밍 비디오가 실제 재생 중일 때만 동작한다.

        본인인증/로비/로딩 창에서는 HP 게이지 오판으로 입력이 새어 들어가
        사용자 입력을 방해한다(2026-09-07 사고). DOM 비디오 상태로 확정한다.
        """
        try:
            result = self.send("Runtime.evaluate", {
                "expression": "(()=>{const v=document.querySelector('video');"
                              "return !!(v && !v.paused && v.readyState>=2 && v.videoWidth>0)})()",
                "returnByValue": True})
            return result.get("result", {}).get("value") is True
        except (OSError, websocket.WebSocketException, KeyError):
            return False

    def geometry(self):
        return (0, 0, WINDOW_SIZE[0], WINDOW_SIZE[1])

    def pointer(self):
        return (0, 0)  # 실제 마우스와 무관하므로 사용자 양보 판단도 무효 없음

    def stop_pressed(self):
        return False  # 중지는 --stop 상태 파일로만

    def find_and_restore(self):
        # 창 리사이즈/재생성 개념이 없다(뷰포트 오버라이드 폐지).
        return self.geometry()

    def capture(self):
        result = self.send("Page.captureScreenshot", {"format": "png"})
        img = cv2.imdecode(np.frombuffer(base64.b64decode(result["data"]),
                                         np.uint8), cv2.IMREAD_COLOR)
        self._cap_size = (img.shape[1], img.shape[0])
        if self._cap_size != WINDOW_SIZE:
            # 판독 좌표계(1933x1332)로 정규화한다 — 창 크기와 무관해짐.
            img = cv2.resize(img, WINDOW_SIZE, interpolation=cv2.INTER_AREA)
        return img

    def video_css_rect(self, force=False):
        """비디오 엘리먼트의 CSS 픽셀 rect. 창 크기가 바뀌면 같이 바뀌므로
        캐시하되 force로 갱신한다. 조회 실패 시 None(=변환 생략)."""
        if force:
            self._css_rect = None
        if getattr(self, "_css_rect", None) is not None:
            return self._css_rect
        try:
            res = self.send("Runtime.evaluate", {
                "expression": '(()=>{const v=document.querySelector("video");'
                              'if(!v)return null;const b=v.getBoundingClientRect();'
                              'return (b.width>0&&b.height>0)?[b.x,b.y,b.width,b.height]:null})()',
                "returnByValue": True})
            self._css_rect = res.get("result", {}).get("value")
        except Exception:
            self._css_rect = None
        return self._css_rect

    def to_css(self, x, y):
        """판독 좌표(1933x1332) → dispatch용 CSS 픽셀 좌표."""
        rect = self.video_css_rect()
        if not rect:
            return round(x), round(y)
        vx, vy, vw, vh = VIDEO_RECT
        cx, cy, cw, ch = rect
        return (round(cx + (x - vx) * cw / vw),
                round(cy + (y - vy) * ch / vh))

    def click(self, x, y, expected_geometry, hover=0.0):
        # 로비/로그인 UI까지 조작해야 하므로 뷰포트 전체를 허용한다.
        # 사냥 좌표 검증(PLAY_RECT)은 호출부(hunt_loop)가 담당한다.
        if not (0 <= x < WINDOW_SIZE[0] and 0 <= y < WINDOW_SIZE[1]):
            raise ValueError("클릭 위치가 뷰포트 밖입니다")
        # dispatch 좌표는 CSS 픽셀(clientX) 기준이고, 입력 좌표는 판독
        # 좌표계(WINDOW_SIZE=1933x1332)다. 이 둘은 1:1이 아니다 —
        # 2026-09-14 실측: innerWidth/Height=2335x1472, 스크린샷=1933x1332.
        # 미변환으로 dispatch하면 배율 1.19만큼 어긋난 지점을 눌러
        # 아이템 라벨 대신 엉뚱한 땅으로 이동한다(줍기 영구 실패의 원인).
        # 비디오 rect를 런타임 조회해 아핀 변환하므로 창 크기가 바뀌어도
        # 따라간다(하드코딩 배율 금지).
        # 웹플레이(모바일 클라이언트 스트리밍)는 마우스가 아니라 터치 입력을
        # 소비한다(실측: dispatchTouchEvent만 이동/조작 반응, 마우스 무반응).
        rx, ry = self.to_css(x, y)
        self.send("Input.dispatchTouchEvent",
                  {"type": "touchStart", "touchPoints": [{"x": rx, "y": ry, "id": 1}]})
        time.sleep(0.12)
        self.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})

    def key(self, name, expected_geometry):
        if name not in {f"F{i}" for i in range(1, 9)}:
            raise ValueError("물약 키는 확인된 F1~F8만 사용할 수 있습니다")
        vk = F_KEYCODES[name]
        common = {"key": name, "code": name, "windowsVirtualKeyCode": vk,
                  "nativeVirtualKeyCode": vk}
        self.send("Input.dispatchKeyEvent", {**common, "type": "keyDown"})
        self.send("Input.dispatchKeyEvent", {**common, "type": "keyUp"})

    def hotkey(self, combo):
        """Alt+W/Alt+G 조합 키를 게임에 전달한다(ATS 설정/시작).

        CDP modifiers 비트: Alt=1, Ctrl=2, Meta=4, Shift=8. 웹플레이가 이
        경로를 소비할지는 미실측이라, 호출부는 클릭 폴백을 함께 둔다.
        """
        parts = [p.strip() for p in combo.split("+")]
        key = parts[-1].lower()
        if not key.isalnum() or len(key) != 1:
            raise ValueError("조합 키는 한 글자 알파벳만 지원합니다")
        modifiers = 0
        for modifier in parts[:-1]:
            modifiers += {"alt": 1, "ctrl": 2, "control": 2,
                          "shift": 8, "meta": 4}.get(modifier.lower(), 0)
        code = "Key" + key.upper()
        vk = ord(key.upper())
        common = {"key": key, "code": code, "windowsVirtualKeyCode": vk,
                  "nativeVirtualKeyCode": vk, "modifiers": modifiers}
        self.send("Input.dispatchKeyEvent", {**common, "type": "keyDown"})
        self.send("Input.dispatchKeyEvent", {**common, "type": "keyUp"})

    def close(self):
        try:
            self.ws.close()
        except OSError:
            pass
