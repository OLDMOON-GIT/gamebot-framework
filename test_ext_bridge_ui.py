"""ext_bridge /ui 채널 테스트 — 확장 팝업이 봇을 켜고/끄고/로그를 받는 경로.

실제 cycle_bot 대신 가짜 봇 스크립트(FAKE_BOT)를 bridge.bot_cmd 로 끼운다.
가짜 봇은 cycle_bot main 과 같은 형식으로 로그를 찍고, STOP_PATH 가 생기면
스스로 종료한다(cycle_bot 의 manager_stop 귀환 경로 흉내).
"""
from __future__ import annotations

import asyncio
import json
import sys
import textwrap
from pathlib import Path

import pytest
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ext_bridge  # noqa: E402
from test_ext_bridge import BridgeThread, FakeExtension, wait_until  # noqa: E402

FAKE_BOT = textwrap.dedent("""
    import os, sys, time
    stop = sys.argv[sys.argv.index("--stop") + 1]
    print("2026-09-10 11:00:00,000 [TOWN] 시작 args=" + " ".join(sys.argv[1:]), flush=True)
    print("2026-09-10 11:00:01,000 [ATS_HUNT] 감시 중", flush=True)
    if "--hang" in sys.argv:
        while True: time.sleep(0.1)
    for _ in range(600):
        if os.path.exists(stop):
            print("2026-09-10 11:00:02,000 [RETURN] 귀환 완료 원인=manager_stop", flush=True)
            sys.exit(0)
        time.sleep(0.02)
    sys.exit(3)
""")


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    stop = tmp_path / "stop"
    monkeypatch.setattr(ext_bridge, "BOT_STOP_PATH", stop)
    monkeypatch.setattr(ext_bridge, "BOT_STOP_GRACE", 0.5)
    script = tmp_path / "fake_bot.py"
    script.write_text(FAKE_BOT)
    bt = BridgeThread()
    bt.bridge.bot_cmd = [sys.executable, "-u", str(script), "--stop", str(stop)]
    bt.start()
    yield bt
    proc = bt.bridge.bot_proc
    if proc is not None and proc.returncode is None:
        proc.kill()
    bt.stop()


class UiClient:
    """팝업 흉내 — 동기 래퍼. 받은 메시지는 전부 inbox 에 쌓인다."""

    def __init__(self, port, origin="chrome-extension://fakeextensionid"):
        self.loop = asyncio.new_event_loop()
        self.ws = self.loop.run_until_complete(websockets.connect(
            f"ws://127.0.0.1:{port}/ui", origin=origin))
        self.inbox = []
        self._id = 0

    def drain(self, timeout=0.3):
        """timeout 동안 도착하는 메시지를 모두 inbox 에 넣는다(총 시간 상한)."""
        async def _d():
            deadline = self.loop.time() + timeout
            while True:
                left = deadline - self.loop.time()
                if left <= 0:
                    return
                try:
                    raw = await asyncio.wait_for(self.ws.recv(), left)
                except asyncio.TimeoutError:
                    return
                self.inbox.append(json.loads(raw))
        self.loop.run_until_complete(_d())

    def call(self, cmd, **kw):
        self._id += 1
        rid = self._id
        self.loop.run_until_complete(self.ws.send(json.dumps({"id": rid, "cmd": cmd, **kw})))

        async def _wait():
            while True:
                msg = json.loads(await asyncio.wait_for(self.ws.recv(), 5))
                self.inbox.append(msg)
                if msg.get("id") == rid:
                    return msg
        return self.loop.run_until_complete(_wait())

    def logs(self):
        out = []
        for m in self.inbox:
            if m.get("type") == "log":
                out.append(m["line"])
            elif m.get("type") == "log_snapshot":
                out.extend(m["lines"])
        return out

    def close(self):
        self.loop.run_until_complete(self.ws.close())
        self.loop.close()


def test_ui_rejects_web_origin(bridge):
    with pytest.raises(websockets.exceptions.InvalidStatus) as ei:
        UiClient(bridge.port, origin="https://evil.example")
    assert ei.value.response.status_code == 403


def test_ui_initial_status_and_snapshot(bridge):
    ui = UiClient(bridge.port)
    try:
        ui.drain()
        types = [m["type"] for m in ui.inbox]
        assert types[:2] == ["status", "log_snapshot"]
        st = ui.inbox[0]
        assert st["ext"] is False
        assert st["bot"]["running"] is False
        assert st["bot"]["state"] is None
    finally:
        ui.close()


def test_start_refused_without_extension(bridge):
    ui = UiClient(bridge.port)
    try:
        r = ui.call("start")
        assert r["ok"] is False and "확장" in r["error"]
        assert bridge.bridge.bot_proc is None
    finally:
        ui.close()


def test_start_streams_log_and_state_then_graceful_stop(bridge):
    ext = FakeExtension(bridge.port).start()
    ui = UiClient(bridge.port)
    try:
        r = ui.call("start", seconds=120, interval=1.5)
        assert r["ok"] is True and r["pid"] > 0
        assert wait_until(lambda: bridge.bridge.bot_state == "ATS_HUNT")
        # 두 번째 start 는 거부
        assert ui.call("start")["ok"] is False
        ui.drain(0.3)
        lines = ui.logs()
        assert any("--seconds 120.0" in l and "--interval 1.5" in l for l in lines), lines
        assert any("[ATS_HUNT] 감시 중" in l for l in lines)
        st = ui.call("status")
        assert st["bot"]["running"] is True and st["bot"]["state"] == "ATS_HUNT"
        assert st["ext"] is True

        r = ui.call("stop")
        assert r == {"ok": True, "mode": "graceful", "type": "reply", "id": r["id"]}
        assert ext_bridge.BOT_STOP_PATH.exists()
        # 가짜 봇이 stop 파일을 보고 스스로 나간다 (terminate 아님)
        assert wait_until(lambda: bridge.bridge.bot_exit is not None)
        assert bridge.bridge.bot_exit == 0
        ui.drain(0.3)
        lines = ui.logs()
        assert any("[RETURN] 귀환 완료 원인=manager_stop" in l for l in lines)
        assert any("봇 종료 (exit=0)" in l for l in lines)
        assert bridge.bridge.bot_state == "RETURN"
        st = ui.call("status")
        assert st["bot"]["running"] is False and st["bot"]["exit"] == 0
        # 재시작 가능 + stop 파일은 새 시작 때 치워진다
        assert ui.call("start")["ok"] is True
        assert not ext_bridge.BOT_STOP_PATH.exists()
    finally:
        ui.close()
        ext.stop()


def test_stop_escalates_to_terminate_when_bot_ignores_stop_file(bridge):
    bridge.bridge.bot_cmd.append("--hang")
    ext = FakeExtension(bridge.port).start()
    ui = UiClient(bridge.port)
    try:
        assert ui.call("start")["ok"] is True
        assert wait_until(lambda: bridge.bridge.bot_state == "ATS_HUNT")
        assert ui.call("stop")["mode"] == "graceful"
        assert wait_until(lambda: bridge.bridge.bot_exit is not None, timeout=3)
        assert bridge.bridge.bot_exit != 0          # SIGTERM 으로 죽음
        ui.drain(0.3)
        assert any("terminate" in l for l in ui.logs())
    finally:
        ui.close()
        ext.stop()


def test_force_stop_and_stop_without_bot(bridge):
    ext = FakeExtension(bridge.port).start()
    ui = UiClient(bridge.port)
    try:
        assert ui.call("stop")["ok"] is False
        assert ui.call("start")["ok"] is True
        assert ui.call("stop", force=True)["mode"] == "terminate"
        assert wait_until(lambda: bridge.bridge.bot_exit is not None)
        assert not ext_bridge.BOT_STOP_PATH.exists()
    finally:
        ui.close()
        ext.stop()


def test_tabs_marks_attached_and_unknown_cmd(bridge):
    ext = FakeExtension(bridge.port, tabs=[
        {"id": 7, "url": "https://purpleon.plaync.com/webplay/linclassic",
         "title": "리니지 클래식", "attached": True}]).start()
    ui = UiClient(bridge.port)
    try:
        r = ui.call("tabs")
        assert r["ok"] is True and r["tabs"][0]["attached"] is True
        assert ui.call("nope")["ok"] is False
    finally:
        ui.close()
        ext.stop()


def test_status_pushed_periodically(bridge, monkeypatch):
    ui = UiClient(bridge.port)
    try:
        ui.drain(ext_bridge.UI_STATUS_INTERVAL + 0.6)
        assert sum(1 for m in ui.inbox if m["type"] == "status") >= 2
    finally:
        ui.close()
