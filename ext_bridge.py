"""크롬 익스텐션 ↔ 봇 브리지 (BTS-1033280).

크롬을 --remote-debugging-port 로 띄우지 않고, 일반 크롬에 올린 확장
(linc-bot/extension)이 chrome.debugger 로 퍼플온 탭에 붙는다. 이 브리지는
한 포트(기본 9335)에서 두 종류의 접속을 받는다.

  * ws  /ext                 — 확장(서비스워커). 한 개만 유지(새 접속이 대체).
  * GET /json, /json/list    — 크롬 원격 디버깅과 같은 탭 목록 JSON.
  * ws  /devtools/page/<id>  — 봇. CDP 메시지 {id, method, params} 를 확장에
                               중계하고 응답을 봇 id 로 되돌려 준다.

즉 cdp_window.CdpWindow(port=9335) 가 코드 수정 없이 그대로 붙는다.
여러 봇 스크립트(cycle_bot, aden_picker, ats_keeper …)가 동시에 붙어도
브리지가 id 를 전역으로 다시 매겨 응답을 각자에게 돌려준다.
디버거 이벤트(id 없는 메시지)는 붙어 있는 모든 봇에게 뿌린다.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import logging
import os
import re
import sys
import time
from http import HTTPStatus
from pathlib import Path

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

BRIDGE_PORT = 9335
EXT_PATH = "/ext"
UI_PATH = "/ui"                 # 확장 팝업 UI 제어 채널 (BTS-1033280 후속)
UI_LOG_LINES = 300              # 팝업에 유지하는 봇 로그 줄 수
UI_STATUS_INTERVAL = 2.0        # 팝업 상태 푸시 주기(초)
BOT_STOP_GRACE = 12.0           # stop 파일 이후 종료 대기(초), 넘기면 terminate
BOT_DIR = Path(__file__).resolve().parent
BOT_STOP_PATH = Path("/tmp/linc-cycle/stop")   # cycle_bot.STOP_PATH 와 동일
PAGE_PREFIX = "/devtools/page/"
TABS_TIMEOUT = 3.0
COMMAND_TIMEOUT = 30.0

log = logging.getLogger("ext_bridge")
_STATE_RE = re.compile(r"^(?:\S+ \S+ )?\[([A-Z][A-Z_]*)\] ")


class Bridge:
    def __init__(self, host: str = "127.0.0.1", port: int = BRIDGE_PORT):
        self.host = host
        self.port = port
        self.ext = None            # 확장 연결
        self.bots: set = set()     # 봇 연결
        self.next_id = 0
        # 전역 id -> (봇 연결 또는 None(브리지 자체), 봇 id 또는 Future)
        self.pending: dict[int, tuple] = {}
        self.server = None
        # ---- UI(팝업) 제어 채널 ----
        self.ui_clients: set = set()
        self.bot_proc = None                  # asyncio.subprocess.Process
        self.bot_started_at: float | None = None
        self.bot_state: str | None = None     # 로그의 "[STATE]" 에서 추출
        self.bot_last: str = ""
        self.bot_exit: int | None = None
        self.bot_log: collections.deque = collections.deque(maxlen=UI_LOG_LINES)
        # 테스트에서 가짜 봇으로 바꿔치기 (argv 리스트)
        self.bot_cmd: list[str] = [sys.executable, "-u", str(BOT_DIR / "cycle_bot.py"), "--ext"]
        self._status_task = None

    # ---------- 확장 쪽 ----------
    async def call_ext(self, method: str, params: dict | None = None,
                       timeout: float = COMMAND_TIMEOUT) -> dict:
        """브리지 자체가 확장에 명령을 보내고 결과를 기다린다."""
        if self.ext is None:
            raise RuntimeError("확장이 연결되어 있지 않습니다")
        self.next_id += 1
        gid = self.next_id
        fut = asyncio.get_running_loop().create_future()
        self.pending[gid] = (None, fut)
        await self.ext.send(json.dumps({"id": gid, "method": method,
                                        "params": params or {}}))
        try:
            resp = await asyncio.wait_for(fut, timeout)
        finally:
            self.pending.pop(gid, None)
        if "error" in resp:
            raise RuntimeError(f"확장 {method} 오류: {resp['error']}")
        return resp.get("result", {})

    async def _fail_pending(self, reason: str) -> None:
        for gid, (bot, ref) in list(self.pending.items()):
            self.pending.pop(gid, None)
            err = {"error": {"code": -32001, "message": reason}}
            if bot is None:
                if not ref.done():
                    ref.set_result(err)
            else:
                try:
                    await bot.send(json.dumps({"id": ref, **err}))
                except ConnectionClosed:
                    pass

    async def serve_ext(self, conn) -> None:
        if self.ext is not None and self.ext is not conn:
            log.info("확장 재접속 — 이전 연결 교체")
            old = self.ext
            self.ext = None
            await self._fail_pending("확장 재접속으로 취소됨")
            try:
                await old.close()
            except Exception:
                pass
        self.ext = conn
        log.info("확장 연결")
        try:
            async for raw in conn:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if "id" in msg and msg["id"] in self.pending:
                    bot, ref = self.pending.pop(msg["id"])
                    if bot is None:
                        if not ref.done():
                            ref.set_result(msg)
                    else:
                        out = dict(msg)
                        out["id"] = ref
                        try:
                            await bot.send(json.dumps(out))
                        except ConnectionClosed:
                            pass
                elif "method" in msg:
                    if msg["method"] == "Bridge.hello":
                        log.info("확장 hello %s", msg.get("params"))
                        continue
                    # 디버거 이벤트 → 모든 봇에 브로드캐스트
                    for bot in list(self.bots):
                        try:
                            await bot.send(raw)
                        except ConnectionClosed:
                            pass
        finally:
            if self.ext is conn:
                self.ext = None
                log.info("확장 끊김")
                await self._fail_pending("확장 연결 끊김")

    # ---------- 봇 쪽 ----------
    async def serve_bot(self, conn) -> None:
        self.bots.add(conn)
        log.info("봇 연결 (%d개)", len(self.bots))
        try:
            async for raw in conn:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                bot_id = msg.get("id")
                if bot_id is None or "method" not in msg:
                    continue
                if self.ext is None:
                    await conn.send(json.dumps({
                        "id": bot_id,
                        "error": {"code": -32001,
                                  "message": "확장이 연결되어 있지 않습니다"}}))
                    continue
                self.next_id += 1
                gid = self.next_id
                self.pending[gid] = (conn, bot_id)
                fwd = {"id": gid, "method": msg["method"],
                       "params": msg.get("params") or {}}
                try:
                    await self.ext.send(json.dumps(fwd))
                except ConnectionClosed:
                    self.pending.pop(gid, None)
                    await conn.send(json.dumps({
                        "id": bot_id,
                        "error": {"code": -32001, "message": "확장 연결 끊김"}}))
        finally:
            self.bots.discard(conn)
            for gid, (bot, _) in list(self.pending.items()):
                if bot is conn:
                    self.pending.pop(gid, None)
            log.info("봇 끊김 (%d개)", len(self.bots))

    # ---------- UI(팝업) 제어 ----------
    def bot_running(self) -> bool:
        return self.bot_proc is not None and self.bot_proc.returncode is None

    def ui_status(self) -> dict:
        return {
            "type": "status",
            "ext": self.ext is not None,
            "bots": len(self.bots),
            "bot": {
                "running": self.bot_running(),
                "pid": self.bot_proc.pid if self.bot_proc else None,
                "state": self.bot_state,
                "last": self.bot_last,
                "started_at": self.bot_started_at,
                "uptime": (time.time() - self.bot_started_at)
                          if self.bot_running() and self.bot_started_at else None,
                "exit": self.bot_exit,
                "stop_requested": BOT_STOP_PATH.exists(),
            },
        }

    async def ui_broadcast(self, msg: dict) -> None:
        if not self.ui_clients:
            return
        data = json.dumps(msg, ensure_ascii=False)
        for ui in list(self.ui_clients):
            try:
                await ui.send(data)
            except ConnectionClosed:
                self.ui_clients.discard(ui)

    def _note_bot_line(self, line: str) -> None:
        self.bot_log.append(line)
        self.bot_last = line
        # cycle_bot main: logging.info("[%s] %s", bot.state, message)
        # → "2026-09-10 11:00:00,123 [ATS_HUNT] ..." (asctime 뒤 대문자 상태 토큰)
        m = _STATE_RE.match(line)
        if m:
            self.bot_state = m.group(1)

    async def _pump_bot_output(self, proc) -> None:
        assert proc.stdout is not None
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace").rstrip("\n")
            self._note_bot_line(line)
            await self.ui_broadcast({"type": "log", "line": line})
        code = await proc.wait()
        if self.bot_proc is proc:
            self.bot_exit = code
            self._note_bot_line(f"[bridge] 봇 종료 (exit={code})")
            await self.ui_broadcast({"type": "log", "line": self.bot_last})
            await self.ui_broadcast(self.ui_status())

    async def bot_start(self, seconds: float | None = None,
                        interval: float | None = None) -> dict:
        if self.bot_running():
            return {"ok": False, "error": "봇이 이미 실행 중입니다"}
        if self.ext is None:
            return {"ok": False, "error": "확장이 연결되어 있지 않습니다 (퍼플 탭 attach 필요)"}
        cmd = list(self.bot_cmd)
        if seconds is not None:
            cmd += ["--seconds", str(float(seconds))]
        if interval is not None:
            cmd += ["--interval", str(float(interval))]
        BOT_STOP_PATH.unlink(missing_ok=True)
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(BOT_DIR), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        self.bot_proc = proc
        self.bot_started_at = time.time()
        self.bot_state = None
        self.bot_exit = None
        self.bot_log.clear()
        self._note_bot_line(f"[bridge] 봇 시작 pid={proc.pid}: {' '.join(cmd)}")
        asyncio.get_running_loop().create_task(self._pump_bot_output(proc))
        log.info("봇 시작 pid=%d", proc.pid)
        await self.ui_broadcast(self.ui_status())
        return {"ok": True, "pid": proc.pid}

    async def bot_stop(self, force: bool = False) -> dict:
        proc = self.bot_proc
        if proc is None or proc.returncode is not None:
            return {"ok": False, "error": "실행 중인 봇이 없습니다"}
        if force:
            proc.terminate()
            self._note_bot_line("[bridge] 강제 종료(terminate) 요청")
            return {"ok": True, "mode": "terminate"}
        # cycle_bot 은 매 스텝 STOP_PATH 를 보고 스스로 빠져나온다(귀환 사유 manager_stop).
        BOT_STOP_PATH.parent.mkdir(parents=True, exist_ok=True)
        BOT_STOP_PATH.touch()
        self._note_bot_line("[bridge] 중지 요청(stop 파일)")
        await self.ui_broadcast(self.ui_status())

        async def _escalate():
            try:
                await asyncio.wait_for(proc.wait(), BOT_STOP_GRACE)
            except asyncio.TimeoutError:
                if proc.returncode is None:
                    proc.terminate()
                    self._note_bot_line(
                        f"[bridge] {BOT_STOP_GRACE:.0f}s 내 미종료 → terminate")
                    await self.ui_broadcast({"type": "log", "line": self.bot_last})
        asyncio.get_running_loop().create_task(_escalate())
        return {"ok": True, "mode": "graceful"}

    async def _status_pusher(self) -> None:
        while True:
            await asyncio.sleep(UI_STATUS_INTERVAL)
            if self.ui_clients:
                await self.ui_broadcast(self.ui_status())

    async def serve_ui(self, conn) -> None:
        self.ui_clients.add(conn)
        try:
            await conn.send(json.dumps(self.ui_status(), ensure_ascii=False))
            await conn.send(json.dumps(
                {"type": "log_snapshot", "lines": list(self.bot_log)}, ensure_ascii=False))
            async for raw in conn:
                try:
                    msg = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                cmd = msg.get("cmd") if isinstance(msg, dict) else None
                rid = msg.get("id") if isinstance(msg, dict) else None
                if cmd == "status":
                    reply = self.ui_status()
                elif cmd == "start":
                    reply = await self.bot_start(msg.get("seconds"), msg.get("interval"))
                elif cmd == "stop":
                    reply = await self.bot_stop(force=bool(msg.get("force")))
                elif cmd == "tabs":
                    reply = {"ok": True, "tabs": await self.tabs_json()}
                else:
                    reply = {"ok": False, "error": f"알 수 없는 명령: {cmd!r}"}
                reply = dict(reply)
                reply.setdefault("type", "reply")
                if rid is not None:
                    reply["id"] = rid
                await conn.send(json.dumps(reply, ensure_ascii=False))
        except ConnectionClosed:
            pass
        finally:
            self.ui_clients.discard(conn)

    # ---------- 라우팅 ----------
    async def tabs_json(self) -> list[dict]:
        if self.ext is None:
            return []
        try:
            result = await self.call_ext("Bridge.tabs", timeout=TABS_TIMEOUT)
        except (RuntimeError, asyncio.TimeoutError) as exc:
            log.warning("탭 목록 실패: %s", exc)
            return []
        out = []
        for t in result.get("tabs", []):
            tid = f"ext-{t.get('id')}"
            out.append({
                "id": tid,
                "type": "page",
                "url": t.get("url", ""),
                "title": t.get("title", ""),
                "attached": bool(t.get("attached")),
                "webSocketDebuggerUrl":
                    f"ws://{self.host}:{self.port}{PAGE_PREFIX}{tid}",
            })
        return out

    async def process_request(self, conn, request):
        path = request.path.split("?", 1)[0]
        upgrade = (request.headers.get("Upgrade") or "").lower()
        if upgrade == "websocket":
            # BTS-1033280 리뷰: 브라우저 페이지 JS 는 ws://127.0.0.1 에 자유롭게 붙을 수
            # 있고 Origin 을 위조하지 못한다. 그래서 Origin 으로 발신자를 가른다.
            #  - /ext          : 확장 서비스워커만 (Origin=chrome-extension://...)
            #  - /devtools/... : 봇(파이썬 websockets, Origin 없음)만. Origin 이 있으면
            #                    웹페이지 → 게임 탭 원격조종 시도이므로 거부.
            origin = request.headers.get("Origin") or ""
            if path == EXT_PATH:
                if origin.startswith("chrome-extension://"):
                    return None
                log.warning("/ext 거부 Origin=%r", origin)
                return conn.respond(HTTPStatus.FORBIDDEN, "forbidden\n")
            if path == UI_PATH:
                # 팝업 페이지도 Origin=chrome-extension://... 이다. 웹페이지가 봇을
                # 켜고 끄지 못하게 같은 기준으로 가른다.
                if origin.startswith("chrome-extension://"):
                    return None
                log.warning("/ui 거부 Origin=%r", origin)
                return conn.respond(HTTPStatus.FORBIDDEN, "forbidden\n")
            if path.startswith(PAGE_PREFIX):
                if not origin:
                    return None
                log.warning("bot 경로 거부 Origin=%r", origin)
                return conn.respond(HTTPStatus.FORBIDDEN, "forbidden\n")
            return conn.respond(HTTPStatus.NOT_FOUND, "not found\n")
        if path in ("/json", "/json/list"):
            body = json.dumps(await self.tabs_json())
            resp = conn.respond(HTTPStatus.OK, body)
            resp.headers["Content-Type"] = "application/json"
            return resp
        if path == "/json/version":
            resp = conn.respond(HTTPStatus.OK, json.dumps({
                "Browser": "linc-bot ext_bridge",
                "Protocol-Version": "1.3",
                "extensionConnected": self.ext is not None}))
            resp.headers["Content-Type"] = "application/json"
            return resp
        return conn.respond(HTTPStatus.NOT_FOUND, "not found\n")

    async def handler(self, conn) -> None:
        path = conn.request.path.split("?", 1)[0]
        if path == EXT_PATH:
            await self.serve_ext(conn)
        elif path == UI_PATH:
            await self.serve_ui(conn)
        elif path.startswith(PAGE_PREFIX):
            await self.serve_bot(conn)

    async def start(self):
        # 캡처 PNG(1933x1332)가 수 MB 라 max_size 를 넉넉히 둔다.
        self.server = await serve(
            self.handler, self.host, self.port,
            process_request=self.process_request,
            max_size=64 * 1024 * 1024, ping_interval=20, ping_timeout=20)
        if self.port == 0:
            self.port = self.server.sockets[0].getsockname()[1]
        self._status_task = asyncio.get_running_loop().create_task(self._status_pusher())
        log.info("브리지 대기 ws://%s:%d (ext=/ext, ui=/ui, bot=/json)", self.host, self.port)
        return self.server

    async def close(self) -> None:
        """서버·상태 푸시·봇 프로세스를 정리한다(테스트/종료 시)."""
        if self._status_task is not None:
            self._status_task.cancel()
            self._status_task = None
        if self.bot_running():
            self.bot_proc.terminate()
            try:
                await asyncio.wait_for(self.bot_proc.wait(), 3)
            except asyncio.TimeoutError:
                self.bot_proc.kill()
        if self.server is not None:
            self.server.close(close_connections=True)
            try:
                await asyncio.wait_for(self.server.wait_closed(), 3)
            except asyncio.TimeoutError:
                pass

    async def run_forever(self):
        await self.start()
        try:
            await self.server.serve_forever()
        finally:
            await self.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=BRIDGE_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        asyncio.run(Bridge(args.host, args.port).run_forever())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
