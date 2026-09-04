"""Minimal Chrome DevTools Protocol client (flatten 세션, 브라우저 WS 경유)."""
import base64
import json
import threading

import requests
import websocket


class CDPClient:
    def __init__(self, ws_url: str, timeout: float = 30.0, session_id: str | None = None):
        self.ws = websocket.create_connection(ws_url, timeout=timeout,
                                              suppress_origin=True,
                                              max_size=100 * 1024 * 1024)
        self.session_id = session_id
        self._id = 0
        self._lock = threading.Lock()

    def call(self, method: str, params: dict | None = None):
        with self._lock:
            self._id += 1
            msg_id = self._id
            msg = {"id": msg_id, "method": method, "params": params or {}}
            if self.session_id:
                msg["sessionId"] = self.session_id
            self.ws.send(json.dumps(msg))
            while True:
                resp = json.loads(self.ws.recv())
                if resp.get("id") == msg_id:
                    if "error" in resp:
                        raise RuntimeError(f"CDP {method}: {resp['error']}")
                    return resp.get("result", {})

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


class PageSession:
    """flatten attach된 페이지 세션 래퍼 (브라우저 WS 공유)."""

    def __init__(self, browser: CDPClient, session_id: str):
        self.browser = browser
        self.session_id = session_id

    def call(self, method: str, params: dict | None = None):
        with self.browser._lock:
            self.browser._id += 1
            msg_id = self.browser._id
            self.browser.ws.send(json.dumps({
                "id": msg_id, "method": method, "params": params or {},
                "sessionId": self.session_id}))
            while True:
                resp = json.loads(self.browser.ws.recv())
                if resp.get("id") == msg_id and \
                        resp.get("sessionId") == self.session_id:
                    if "error" in resp:
                        raise RuntimeError(f"CDP {method}: {resp['error']}")
                    return resp.get("result", {})

    def close(self):
        self.browser.close()


def find_page_session(debug_port: int, url_substr: str,
                      timeout: float = 30.0) -> PageSession:
    tabs = requests.get(f"http://127.0.0.1:{debug_port}/json",
                        timeout=5).json()
    target = None
    for tab in tabs:
        if tab.get("type") == "page" and url_substr in tab.get("url", ""):
            target = tab
            break
    if target is None:
        raise RuntimeError(f"'{url_substr}' 탭을 찾지 못함 (열린 탭: "
                           f"{[t.get('url', '')[:60] for t in tabs if t.get('type') == 'page']})")
    ver = requests.get(f"http://127.0.0.1:{debug_port}/json/version",
                       timeout=5).json()
    browser = CDPClient(ver["webSocketDebuggerUrl"], timeout=timeout)
    r = browser.call("Target.attachToTarget",
                     {"targetId": target["id"], "flatten": True})
    return PageSession(browser, r["sessionId"])


class Input:
    """CDP trusted input injection."""

    def __init__(self, cdp):
        self.cdp = cdp

    def click(self, x: int, y: int, button: str = "left"):
        for t in ("mouseMoved", "mousePressed", "mouseReleased"):
            p = {"type": t, "x": x, "y": y, "button": button, "clickCount": 1}
            self.cdp.call("Input.dispatchMouseEvent", p)

    def key(self, key: str, code: str, key_code: int):
        for t in ("keyDown", "keyUp"):
            self.cdp.call("Input.dispatchKeyEvent", {
                "type": t, "key": key, "code": code,
                "windowsVirtualKeyCode": key_code,
                "nativeVirtualKeyCode": key_code})


# 자주 쓰는 키 매핑 (Windows VK 코드)
KEYMAP = {
    "1": ("1", "Digit1", 0x31), "2": ("2", "Digit2", 0x32),
    "3": ("3", "Digit3", 0x33), "4": ("4", "Digit4", 0x34),
    "5": ("5", "Digit5", 0x35), "6": ("6", "Digit6", 0x36),
    "F1": ("F1", "F1", 0x70), "F2": ("F2", "F2", 0x71),
    "F3": ("F3", "F3", 0x72), "F4": ("F4", "F4", 0x73),
    "F5": ("F5", "F5", 0x74), "F6": ("F6", "F6", 0x75),
    "F7": ("F7", "F7", 0x76), "F8": ("F8", "F8", 0x77),
    "SPACE": (" ", "Space", 0x20),
}


def press(inp: Input, name: str):
    k, c, vk = KEYMAP[name]
    inp.key(k, c, vk)


def screenshot_b64(cdp, quality: int = 70) -> bytes:
    r = cdp.call("Page.captureScreenshot",
                 {"format": "jpeg", "quality": quality})
    return base64.b64decode(r["data"])
