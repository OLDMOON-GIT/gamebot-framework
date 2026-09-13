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
import json
import logging
import sys
from http import HTTPStatus

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

BRIDGE_PORT = 9335
EXT_PATH = "/ext"
PAGE_PREFIX = "/devtools/page/"
TABS_TIMEOUT = 3.0
COMMAND_TIMEOUT = 30.0

log = logging.getLogger("ext_bridge")


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
        log.info("브리지 대기 ws://%s:%d (ext=/ext, bot=/json)", self.host, self.port)
        return self.server

    async def run_forever(self):
        await self.start()
        await self.server.serve_forever()


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
