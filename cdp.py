"""Minimal Chrome DevTools Protocol client (no external deps beyond websocket-client)."""
import base64
import json
import threading

import requests
import websocket


class CDPClient:
    def __init__(self, ws_url: str, timeout: float = 30.0):
        self.ws = websocket.create_connection(ws_url, timeout=timeout,
                                              suppress_origin=True,
                                              max_size=100 * 1024 * 1024)
        self._id = 0
        self._lock = threading.Lock()

    def call(self, method: str, params: dict | None = None):
        with self._lock:
            self._id += 1
            msg_id = self._id
            self.ws.send(json.dumps({"id": msg_id, "method": method,
                                     "params": params or {}}))
            while True:
                msg = json.loads(self.ws.recv())
                if msg.get("id") == msg_id:
                    if "error" in msg:
                        raise RuntimeError(f"CDP {method}: {msg['error']}")
                    return msg.get("result", {})

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def find_page_ws(debug_port: int, url_substr: str) -> str:
    tabs = requests.get(f"http://127.0.0.1:{debug_port}/json",
                        timeout=5).json()
    for tab in tabs:
        if tab.get("type") == "page" and url_substr in tab.get("url", ""):
            return tab["webSocketDebuggerUrl"]
    raise RuntimeError(f"'{url_substr}' 탭을 찾지 못함 (열린 탭: "
                       f"{[t.get('url', '')[:60] for t in tabs if t.get('type') == 'page']})")


class Input:
    """CDP trusted input injection."""

    def __init__(self, cdp: CDPClient):
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


def screenshot_b64(cdp: CDPClient, quality: int = 70) -> bytes:
    r = cdp.call("Page.captureScreenshot",
                 {"format": "jpeg", "quality": quality})
    return base64.b64decode(r["data"])
