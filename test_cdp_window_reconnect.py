"""BTS-1033015: 끊어진 CDP 소켓을 send()가 스스로 복구하는지 검증.

실측 실패: 브리지가 조용히 닫히면 recv()가 빈 문자열을 반환해
json.loads('')가 "Expecting value: line 1 column 1 (char 0)"로 터지고,
그 예외가 사냥 메인 루프까지 올라가 전체 재초기화를 유발했다
(/tmp/onestep_hunt.log 17분간 10회).
"""
import json
import unittest

import websocket

from cdp_window import CdpWindow


class FakeWs:
    """지정한 시나리오대로 응답/예외를 내는 웹소켓 스텁."""

    def __init__(self, mode="ok"):
        self.mode = mode
        self.sent = []
        self.closed = False

    def send(self, payload):
        if self.mode == "broken_pipe":
            raise BrokenPipeError(32, "Broken pipe")
        self.sent.append(json.loads(payload))

    def recv(self):
        if self.mode == "empty":
            return ""  # 상대가 닫은 소켓
        last_id = self.sent[-1]["id"]
        if self.mode == "cdp_error":
            return json.dumps({"id": last_id,
                               "error": {"message": "잘못된 파라미터"}})
        return json.dumps({"id": last_id, "result": {"ok": True}})

    def close(self):
        self.closed = True


def make_window(mode):
    """__init__(실제 네트워크)을 우회해 send() 로직만 검사한다."""
    win = CdpWindow.__new__(CdpWindow)
    win.port = 9222
    win.url_prefix = "purpleon"
    win.msg_id = 0
    win.ws = FakeWs(mode)
    win.reconnects = 0

    def fake_connect(_self=win, healthy=True):
        _self.reconnects += 1
        _self.ws = FakeWs("ok" if healthy else _self.ws.mode)

    win._connect = fake_connect
    return win


class TestSendReconnect(unittest.TestCase):
    def test_정상응답은_재접속하지_않는다(self):
        win = make_window("ok")
        self.assertEqual(win.send("Page.captureScreenshot"), {"ok": True})
        self.assertEqual(win.reconnects, 0)

    def test_빈응답이면_재접속후_재시도로_성공한다(self):
        win = make_window("empty")
        self.assertEqual(win.send("Page.captureScreenshot"), {"ok": True})
        self.assertEqual(win.reconnects, 1, "빈 응답은 1회 재접속으로 흡수")

    def test_Broken_pipe도_재접속후_재시도로_성공한다(self):
        win = make_window("broken_pipe")
        self.assertEqual(win.send("Input.dispatchMouseEvent"), {"ok": True})
        self.assertEqual(win.reconnects, 1)

    def test_재접속해도_계속_끊기면_예외를_올린다(self):
        win = make_window("empty")
        win._connect = lambda: (
            setattr(win, "reconnects", win.reconnects + 1),
            setattr(win, "ws", FakeWs("empty")),
        )
        with self.assertRaises(websocket.WebSocketException):
            win.send("Page.captureScreenshot")
        self.assertEqual(win.reconnects, 1, "재시도는 정확히 1회만")

    def test_CDP_프로토콜_오류는_재시도하지_않는다(self):
        win = make_window("cdp_error")
        with self.assertRaises(RuntimeError):
            win.send("Input.dispatchKeyEvent")
        self.assertEqual(win.reconnects, 0, "서버가 답한 오류는 재접속 대상 아님")

    def test_active는_복구불가시_False를_돌려준다(self):
        win = make_window("empty")
        win._connect = lambda: (_ for _ in ()).throw(OSError("연결 거부"))
        self.assertFalse(win.active())


if __name__ == "__main__":
    unittest.main(verbosity=2)
