"""ext_bridge 테스트 (BTS-1033280).

가짜 확장(websockets 클라이언트)을 /ext 에 붙이고, 실제 cdp_window.CdpWindow
가 브리지의 /json + devtools ws 를 통해 명령을 주고받는지 검증한다.
브리지는 별도 스레드의 이벤트 루프에서 임시 포트(0)로 돈다.
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ext_bridge  # noqa: E402
from cdp_window import CdpWindow, WINDOW_SIZE  # noqa: E402

PURPLE_URL = "https://purpleon.plaync.com/webplay/linclassic"
# 2x3 PNG (cv2 로 실제 인코딩 — 손으로 쓴 바이트는 디코드 실패)
import cv2  # noqa: E402
import numpy as np  # noqa: E402
PNG_B64 = base64.b64encode(
    cv2.imencode(".png", np.zeros((3, 2, 3), np.uint8))[1].tobytes()).decode()


class BridgeThread:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.bridge = ext_bridge.Bridge("127.0.0.1", 0)
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.bridge.start())
        self.ready.set()
        self.loop.run_forever()

    @property
    def port(self):
        return self.bridge.port

    def start(self):
        self.thread.start()
        assert self.ready.wait(5)
        return self.bridge.port

    async def _shutdown(self):
        self.bridge.server.close(close_connections=True)
        try:
            await asyncio.wait_for(self.bridge.server.wait_closed(), 3)
        except asyncio.TimeoutError:
            pass

    def stop(self):
        asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop).result(5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)

    def run(self, coro, timeout=5):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)


class FakeExtension:
    """확장 서비스워커를 흉내낸다. 받은 명령을 기록하고 handler 결과를 돌려준다."""

    def __init__(self, port, tabs=None, handler=None):
        self.port = port
        self.tabs = tabs if tabs is not None else [
            {"id": 7, "url": PURPLE_URL, "title": "리니지 클래식"}]
        self.handler = handler or self.default_handler
        self.received = []
        self.loop = asyncio.new_event_loop()
        self.ws = None
        self.connected = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.stop_flag = None

    def default_handler(self, msg):
        m = msg["method"]
        if m == "Page.captureScreenshot":
            return {"result": {"data": PNG_B64}}
        if m == "Runtime.evaluate":
            return {"result": {"result": {"type": "number", "value": 42}}}
        if m == "Input.dispatchMouseEvent":
            return {"result": {}}
        return {"error": {"code": -32601, "message": f"unknown {m}"}}

    async def _main(self):
        self.stop_flag = asyncio.Event()
        # 실제 확장 서비스워커는 Origin=chrome-extension://<id> 를 보낸다
        async with websockets.connect(
                f"ws://127.0.0.1:{self.port}/ext", max_size=None,
                origin="chrome-extension://fakeextensionid") as ws:
            self.ws = ws
            await ws.send(json.dumps({"method": "Bridge.hello",
                                      "params": {"version": "test"}}))
            self.connected.set()
            recv = asyncio.ensure_future(ws.recv())
            stop = asyncio.ensure_future(self.stop_flag.wait())
            while True:
                done, _ = await asyncio.wait({recv, stop},
                                             return_when=asyncio.FIRST_COMPLETED)
                if stop in done:
                    recv.cancel()
                    return
                raw = recv.result()
                recv = asyncio.ensure_future(ws.recv())
                msg = json.loads(raw)
                self.received.append(msg)
                if msg["method"] == "Bridge.tabs":
                    reply = {"result": {"tabs": self.tabs}}
                elif msg["method"] == "Bridge.ping":
                    reply = {"result": {"pong": True}}
                else:
                    reply = self.handler(msg)
                if reply is not None:
                    await ws.send(json.dumps({"id": msg["id"], **reply}))

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main())
        except websockets.exceptions.ConnectionClosed:
            pass

    def start(self):
        self.thread.start()
        assert self.connected.wait(5)
        return self

    def emit_event(self, method, params):
        fut = asyncio.run_coroutine_threadsafe(
            self.ws.send(json.dumps({"method": method, "params": params})),
            self.loop)
        fut.result(5)

    def stop(self):
        if self.stop_flag is not None:
            self.loop.call_soon_threadsafe(self.stop_flag.set)
        self.thread.join(5)


@pytest.fixture
def bridge():
    bt = BridgeThread()
    bt.start()
    yield bt
    bt.stop()


def http_json(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as r:
        return json.loads(r.read())


def wait_until(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def test_json_empty_without_extension(bridge):
    assert http_json(bridge.port, "/json") == []
    assert http_json(bridge.port, "/json/version")["extensionConnected"] is False


def test_json_lists_purple_tab_with_devtools_url(bridge):
    ext = FakeExtension(bridge.port).start()
    try:
        tabs = http_json(bridge.port, "/json")
        assert len(tabs) == 1
        assert tabs[0]["url"] == PURPLE_URL
        assert tabs[0]["type"] == "page"
        assert tabs[0]["webSocketDebuggerUrl"] == \
            f"ws://127.0.0.1:{bridge.port}/devtools/page/ext-7"
    finally:
        ext.stop()


def test_cdpwindow_roundtrip_through_bridge(bridge):
    ext = FakeExtension(bridge.port).start()
    try:
        w = CdpWindow(port=bridge.port)
        # Runtime.evaluate 가 확장까지 갔다가 값이 돌아온다
        r = w.send("Runtime.evaluate", {"expression": "6*7"})
        assert r["result"]["value"] == 42
        # 캡처는 PNG 디코드 + WINDOW_SIZE 정규화까지 된다
        frame = w.capture()
        assert w._cap_size == (2, 3)
        assert (frame.shape[1], frame.shape[0]) == WINDOW_SIZE
        # 명령이 확장에 실제 CDP method 로 도달했는지
        methods = [m["method"] for m in ext.received]
        assert "Runtime.evaluate" in methods
        assert "Page.captureScreenshot" in methods
        w.close()
    finally:
        ext.stop()


def test_bot_id_remapped_independently_per_client(bridge):
    ext = FakeExtension(bridge.port).start()
    try:
        a = CdpWindow(port=bridge.port)
        b = CdpWindow(port=bridge.port)
        # 두 봇이 같은 로컬 id(1,2,…)를 쓰지만 각자 자기 응답을 받아야 한다
        seen = {}

        def handler(msg):
            seen[msg["id"]] = msg
            return {"result": {"result": {"type": "string",
                                          "value": msg["params"]["expression"]}}}
        ext.handler = handler
        ev = lambda w, x: w.send("Runtime.evaluate",  # noqa: E731
                                 {"expression": x})["result"]["value"]
        assert ev(a, "A") == "A"
        assert ev(b, "B") == "B"
        assert ev(a, "A2") == "A2"
        # 확장이 받은 전역 id 는 서로 달라야 한다
        assert len(set(seen)) == 3
        a.close(); b.close()
    finally:
        ext.stop()


def test_extension_error_propagates_as_runtime_error(bridge):
    ext = FakeExtension(bridge.port, handler=lambda m: {
        "error": {"code": -32000, "message": "Cannot attach to this target"}}).start()
    try:
        w = CdpWindow(port=bridge.port)
        with pytest.raises(RuntimeError, match="Cannot attach"):
            w.send("Runtime.evaluate", {"expression": "1"})
        w.close()
    finally:
        ext.stop()


def test_command_fails_fast_when_extension_absent(bridge):
    ext = FakeExtension(bridge.port).start()
    w = CdpWindow(port=bridge.port)
    ext.stop()
    assert wait_until(lambda: bridge.bridge.ext is None)
    with pytest.raises(RuntimeError, match="확장이 연결되어 있지 않습니다"):
        w.send("Runtime.evaluate", {"expression": "1"})
    w.close()


def test_pending_command_failed_when_extension_drops(bridge):
    # 확장이 응답하지 않는 상태에서 끊기면 대기 중이던 봇 명령에 오류가 간다
    ext = FakeExtension(bridge.port, handler=lambda m: None).start()
    w = CdpWindow(port=bridge.port)
    result = {}

    def call():
        try:
            w.send("Runtime.evaluate", {"expression": "1"})
        except Exception as exc:  # noqa: BLE001
            result["exc"] = exc
    t = threading.Thread(target=call, daemon=True)
    t.start()
    assert wait_until(lambda: any(
        m["method"] == "Runtime.evaluate" for m in ext.received))
    ext.stop()
    t.join(5)
    assert not t.is_alive()
    assert "확장 연결 끊김" in str(result["exc"])
    w.close()


def test_debugger_events_broadcast_to_bots(bridge):
    ext = FakeExtension(bridge.port).start()
    try:
        w = CdpWindow(port=bridge.port)
        ext.emit_event("Page.frameNavigated", {"frame": {"url": PURPLE_URL}})
        raw = w.ws.recv()
        msg = json.loads(raw)
        assert msg["method"] == "Page.frameNavigated"
        assert "id" not in msg
        w.close()
    finally:
        ext.stop()


def test_new_extension_replaces_old(bridge):
    ext1 = FakeExtension(bridge.port, tabs=[{"id": 1, "url": PURPLE_URL, "title": "old"}]).start()
    ext2 = FakeExtension(bridge.port, tabs=[{"id": 2, "url": PURPLE_URL, "title": "new"}]).start()
    try:
        # 교체 순간에는 잠깐 [] 이 나올 수 있다 — 최종적으로 ext-2 만 보여야 한다
        assert wait_until(lambda: [t["id"] for t in http_json(bridge.port, "/json")] == ["ext-2"])
    finally:
        ext2.stop()
        ext1.stop()


def test_multiple_purple_tabs_rejected_by_cdpwindow(bridge):
    ext = FakeExtension(bridge.port, tabs=[
        {"id": 1, "url": PURPLE_URL, "title": "a"},
        {"id": 2, "url": PURPLE_URL, "title": "b"}]).start()
    try:
        with pytest.raises(RuntimeError, match="2개"):
            CdpWindow(port=bridge.port)
    finally:
        ext.stop()


def test_ext_path_rejects_non_extension_origin(bridge):
    """리뷰: 웹페이지 JS 가 /ext 에 붙어 확장 자리를 가로채는 것을 막는다."""
    async def _try(origin):
        try:
            async with websockets.connect(
                    f"ws://127.0.0.1:{bridge.port}/ext", origin=origin):
                return "accepted"
        except websockets.exceptions.InvalidStatus as exc:
            return exc.response.status_code
    assert asyncio.run(_try("https://evil.example")) == 403
    assert asyncio.run(_try("http://127.0.0.1:9335")) == 403
    # Origin 없는 접속(브라우저 아님)도 /ext 에는 못 붙는다
    assert asyncio.run(_try(None)) == 403


def test_bot_path_rejects_browser_origin(bridge):
    """리뷰: 브라우저 페이지가 봇으로 위장해 게임 탭에 CDP 를 보내는 것을 막는다."""
    ext = FakeExtension(bridge.port); ext.start()
    try:
        assert wait_until(lambda: http_json(bridge.port, "/json"))
        url = http_json(bridge.port, "/json")[0]["webSocketDebuggerUrl"]

        async def _try(origin):
            try:
                async with websockets.connect(url, origin=origin):
                    return "accepted"
            except websockets.exceptions.InvalidStatus as exc:
                return exc.response.status_code
        assert asyncio.run(_try("https://purpleon.plaync.com")) == 403
        assert asyncio.run(_try("chrome-extension://someid")) == 403
        # 파이썬 봇(Origin 없음)은 통과
        assert asyncio.run(_try(None)) == "accepted"
    finally:
        ext.stop()
