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
        self.send("Emulation.setDeviceMetricsOverride", VIEWPORT)

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
        # 창 리사이즈/재생성 개념이 없고 뷰포트는 고정 오버라이드 상태다.
        self.send("Emulation.setDeviceMetricsOverride", VIEWPORT)
        return self.geometry()

    def capture(self):
        result = self.send("Page.captureScreenshot", {"format": "png"})
        img = cv2.imdecode(np.frombuffer(base64.b64decode(result["data"]),
                                         np.uint8), cv2.IMREAD_COLOR)
        if (img.shape[1], img.shape[0]) != WINDOW_SIZE:
            raise RuntimeError(f"CDP 캡처 크기 불일치: {img.shape[1]}x{img.shape[0]}")
        return img

    def click(self, x, y, expected_geometry, hover=0.0):
        # 로비/로그인 UI까지 조작해야 하므로 뷰포트 전체를 허용한다.
        # 사냥 좌표 검증(PLAY_RECT)은 호출부(hunt_loop)가 담당한다.
        if not (0 <= x < WINDOW_SIZE[0] and 0 <= y < WINDOW_SIZE[1]):
            raise ValueError("클릭 위치가 뷰포트 밖입니다")
        # dispatch 좌표는 뷰포트(clientX) 기준이다(실측: 전송값=clientX 1:1).
        # 스트리밍 플레이어가 내부에서 게임 좌표로 변환하므로 여기서는
        # 절대 변환하지 않는다 — to_stream을 여기 넣으면 이중 변환으로
        # 좌표가 비디오 밖으로 나가 클릭이 무시된다(2026-09-07 사고).
        # 웹플레이(모바일 클라이언트 스트리밍)는 마우스가 아니라 터치 입력을
        # 소비한다(실측: dispatchTouchEvent만 이동/조작 반응, 마우스 무반응).
        self.send("Input.dispatchTouchEvent",
                  {"type": "touchStart", "touchPoints": [{"x": x, "y": y, "id": 1}]})
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

    def close(self):
        try:
            self.ws.close()
        except OSError:
            pass
