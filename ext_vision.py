#!/usr/bin/env python3
"""
LINC Vision Bridge - 파이썬 수신기

브라우저 익스텐션(linc-vision-ext)이 보내는 네이티브 프레임을 받아 메모리에 들고 있다가
봇이 요청하면 cv2 이미지로 돌려준다.

화면캡처 방식 대비 이점:
  - 창 크기/전체화면 여부와 무관 (확대·축소 보간이 끼어들지 않음)
  - 다른 창에 가려도, 포커스가 없어도 캡처됨
  - 좌표가 네이티브 1280x960 절대좌표로 고정 → 해상도 바뀌어도 안 깨짐

HUD는 PNG 무손실로 받는다. JPEG q70에서 244가 '294'로 오독되는 것을 실측했기 때문이다.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

DEFAULT_PORT = 17311

# HUD 이미지 원점(네이티브 y=720)을 뺀 내부 좌표. 네이티브 1280x960 기준 실측값.
HUD_ORIGIN_Y = 720
HP_CUR_RECT = (466, 43, 32, 16)   # 네이티브 (466,763,32,16)
HP_MAX_RECT = (506, 43, 36, 16)   # 네이티브 (506,763,36,16)
NATIVE_W, NATIVE_H = 1280, 960

_lock = threading.Lock()
_latest = {}          # kind -> dict(ts, data, native_w, native_h, origin_y)
_server = None
_thread = None


class _Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        kind = self.path.strip('/').lower()
        if kind == 'bot-settings':
            # 크롬 익스텐션 UI 세팅 저장(사용자 지시 2026-09-15): 물약 키/
            # 시작%/목표%/위험% 등. 봇은 다음 체크부터 즉시 반영.
            try:
                n = int(self.headers.get('Content-Length') or 0)
                payload = json.loads(self.rfile.read(n) or b'{}')
                import bot_settings
                saved = bot_settings.save(payload)
            except Exception:
                self.send_response(400)
                self._cors()
                self.end_headers()
                return
            body = json.dumps(saved).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return
        if kind == 'bot-hp':
            # 봇(onestep)이 판독한 HP를 게시 — 확장 UI가 /hp에서 우선
            # 표시한다(2026-09-15: 크롬 익스텐션 HUD UI 데이터 소스).
            try:
                n = int(self.headers.get('Content-Length') or 0)
                payload = json.loads(self.rfile.read(n) or b'{}')
                bot = dict(payload)
                assert isinstance(bot.get('ratio'), (int, float))
            except Exception:
                self.send_response(400)
                self._cors()
                self.end_headers()
                return
            bot['ts'] = time.time()
            with _lock:
                _latest['bot'] = bot
            self.send_response(204)
            self._cors()
            self.end_headers()
            return
        kind = self.path.strip('/').lower()
        if kind == 'ext-ratio':
            # 페이지 주입 판독기(2026-09-15): content.js 확장 갱신 전까지
            # 게임 탭에 CDP로 심은 스크립트가 게이지 폭 판독값을 보낸다.
            try:
                n = int(self.headers.get('Content-Length') or 0)
                payload = json.loads(self.rfile.read(n) or b'{}')
                ratio = float(payload.get('ratio'))
                assert 0.0 <= ratio <= 1.0
            except Exception:
                self.send_response(400)
                self._cors()
                self.end_headers()
                return
            with _lock:
                ent = _latest.setdefault('hud', {})
                ent['hp_ratio'] = ratio
                ent['hp_ratio_ts'] = time.time()
            self.send_response(204)
            self._cors()
            self.end_headers()
            return
        if kind not in ('hud', 'full'):
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = 0
        data = self.rfile.read(n) if n > 0 else b''

        def _int(name, default):
            try:
                return int(self.headers.get(name) or default)
            except (TypeError, ValueError):
                return default

        def _float(name, default):
            try:
                return float(self.headers.get(name) or default)
            except (TypeError, ValueError):
                return default

        with _lock:
            prev = _latest.get('hud') or {}
            _latest[kind] = {
                'ts': time.time(),
                'data': data,
                'native_w': _int('X-Native-W', NATIVE_W),
                'native_h': _int('X-Native-H', NATIVE_H),
                'origin_y': _int('X-Origin-Y', HUD_ORIGIN_Y),
                # 확장 안 게이지 판독값(BTS-1033474). content.js(또는 페이지
                # 주입 판독기 /ext-ratio)가 게이지 채움 폭으로 계산해 보낸다
                # — 숫자 OCR의 자릿수 오독('223'→'23')이 원천 없다. 헤더가
                # 없는 프레임은 기존값을 유지해 주입 판독값을 덮어쓰지 않는다.
                'hp_ratio': (_float('X-HP-Ratio', None)
                             if self.headers.get('X-HP-Ratio')
                             else prev.get('hp_ratio')),
                'hp_ratio_ts': (time.time()
                                if self.headers.get('X-HP-Ratio')
                                else prev.get('hp_ratio_ts', 0)),
            }
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path.startswith('/bot-settings'):
            import bot_settings
            body = json.dumps(bot_settings.load(refresh=0)).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith('/hp'):
            try:
                q = self.path.split('?', 1)[1] if '?' in self.path else ''
                scale = 3
                for kv in q.split('&'):
                    if kv.startswith('scale='):
                        scale = max(1, min(10, int(kv[6:])))
                hp, hp_max = read_hp(max_age=2.0, scale=scale)
            except Exception:
                hp, hp_max = None, None
            # 확장 게이지 판독값(BTS-1033474): 있으면 이쪽이 우선이다.
            ratio = read_ext_ratio(max_age=1.0)
            # 봇 게시값(CDP 화면 판독 — 검증된 안정 경로): UI 표시 우선.
            bot = None
            with _lock:
                ent = _latest.get('bot')
                if ent and time.time() - ent.get('ts', 0) <= 10.0:
                    bot = dict(ent)
            # 확장 즉시 판독(100ms 신선도): UI 동기화 지연 단축용.
            ext_hp = ext_hp_max = None
            with _lock:
                ent = _latest.get('hud') or {}
                if time.time() - ent.get('ext_hp_ts', 0) <= 1.0:
                    ext_hp, ext_hp_max = ent.get('ext_hp'), ent.get('ext_hp_max')
            if ext_hp is not None and ext_hp_max:
                hp, hp_max = ext_hp, ext_hp_max
                if ratio is None and hp_max:
                    ratio = hp / hp_max
            if bot is not None:
                ratio = bot.get('ratio', ratio)
            body = json.dumps(
                {"hp": hp, "hp_max": hp_max, "ratio": ratio,
                 "bot": bot}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith('/frame'):
            kind = 'hud'
            if 'kind=full' in self.path:
                kind = 'full'
            with _lock:
                ent = _latest.get(kind)
                data = ent['data'] if ent else b''
            if not data:
                self.send_response(404)
                self._cors()
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Content-Length', str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path.startswith('/status'):
            body = status_text().encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self._cors()
        self.end_headers()

    def log_message(self, *args):
        pass  # 접근 로그 침묵


def _hp_reader_loop():
    """확장 HUD(video 스트립)를 백그라운드 판독(사용자 지시 2026-09-15
    'HP동기화 100ms'). read_hp는 tesseract 서브프로세스라 ~300ms가 바닥이
    지만 항상 최신 프레임만 읽어 신선도를 유지한다."""
    while True:
        try:
            cur, mx = read_hp(max_age=1.0)
            if cur is not None:
                with _lock:
                    ent = _latest.setdefault('hud', {})
                    ent['ext_hp'], ent['ext_hp_max'] = cur, mx
                    ent['ext_hp_ts'] = time.time()
        except Exception:
            pass
        time.sleep(0.05)


def start_reader_thread():
    import threading
    t = threading.Thread(target=_hp_reader_loop, daemon=True)
    t.start()
    return t


def start(port=DEFAULT_PORT):
    """수신 서버를 백그라운드 스레드로 띄운다. 이미 떠 있으면 그대로 둔다."""
    global _server, _thread
    if _server is not None:
        return _server
    _server = ThreadingHTTPServer(('127.0.0.1', port), _Handler)
    _thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()
    return _server


def stop():
    global _server, _thread
    if _server is not None:
        _server.shutdown()
        _server.server_close()
        _server = None
        _thread = None


def _decode(kind, max_age):
    with _lock:
        ent = _latest.get(kind)
    if not ent:
        return None, None
    if max_age is not None and (time.time() - ent['ts']) > max_age:
        return None, ent
    img = cv2.imdecode(np.frombuffer(ent['data'], np.uint8), cv2.IMREAD_COLOR)
    return img, ent


def get_hud(max_age=0.5):
    """HUD 스트립(무손실 PNG)을 cv2 이미지로 반환. 없거나 오래됐으면 None."""
    img, _ = _decode('hud', max_age)
    return img


def get_full(max_age=1.0):
    """전체 프레임(JPEG)을 cv2 이미지로 반환. 없거나 오래됐으면 None."""
    img, _ = _decode('full', max_age)
    return img


def _scaled(rect, ent, img=None):
    """네이티브 해상도가 1280x960이 아니면 좌표를 비례 보정한다.

    헤더(native_w)가 실제 전송 이미지와 어긋나는 경우가 있어(예: HUD 크롭 폭 고정)
    이미지가 주어지면 이미지 실제 폭을 기준으로 보정한다 — 자가 교정.
    """
    if img is not None and getattr(img, 'shape', None):
        s = img.shape[1] / float(NATIVE_W)
        if abs(s - 1.0) < 1e-6:
            return rect
        x, y, w, h = rect
        return (int(round(x * s)), int(round(y * s)),
                int(round(w * s)), int(round(h * s)))
    if not ent:
        return rect
    sx = ent.get('native_w', NATIVE_W) / float(NATIVE_W)
    sy = ent.get('native_h', NATIVE_H) / float(NATIVE_H)
    if abs(sx - 1.0) < 1e-6 and abs(sy - 1.0) < 1e-6:
        return rect
    x, y, w, h = rect
    return (int(round(x * sx)), int(round(y * sy)),
            int(round(w * sx)), int(round(h * sy)))


def read_ext_ratio(max_age=0.7):
    """확장(content.js)이 게이지 채움 폭으로 계산한 HP 비율.

    BTS-1033474(사용자 지시 'HUD를 크롬익스텐션으로 개발'): 확장 안에서
    판독한 값이며 숫자 OCR의 자릿수 오독('223'→'23' → 0.09 오판 → 봇
    이탈 사고)이 원천 없다. 헤더가 없거나 오래됐으면 None(OCR 폴백).
    """
    with _lock:
        ent = _latest.get('hud')
        if not ent or ent.get('hp_ratio') is None:
            return None
        age = time.time() - ent.get('hp_ratio_ts', ent.get('ts', 0))
        if max_age is not None and age > max_age:
            return None
        ratio = ent['hp_ratio']
    return float(min(1.0, max(0.0, ratio)))


def read_hp(max_age=0.5, scale=3):
    """
    HP 현재/최대를 읽는다. 실패 시 (None, None).

    게이지 길이가 아니라 숫자를 직접 읽는다. 게이지는 만렙 화면에서 방향(좌→우/우→좌)을
    확정할 수 없었고, 숫자는 비트맵 폰트라 네이티브 픽셀에서 100% 읽혔다.
    """
    import linux_vision as lv  # 봇과 완전히 같은 OCR 경로를 쓴다

    img, ent = _decode('hud', max_age)
    if img is None:
        return None, None

    def one(rect):
        x, y, w, h = _scaled(rect, ent, img)
        if y + h > img.shape[0] or x + w > img.shape[1]:
            return None
        txt = lv.ocr(img[y:y + h, x:x + w], whitelist='0123456789', scale=scale)
        if not txt:
            return None
        digits = ''.join(c for c in txt if c.isdigit())
        return int(digits) if digits else None

    cur, mx = one(HP_CUR_RECT), one(HP_MAX_RECT)
    # 말이 안 되는 조합은 버린다 (현재>최대, 0 이하 최대)
    if cur is not None and mx is not None and (mx <= 0 or cur > mx):
        return None, None
    return cur, mx


def status_text():
    now = time.time()
    parts = []
    with _lock:
        for kind in ('hud', 'full'):
            ent = _latest.get(kind)
            if not ent:
                parts.append('%s=없음' % kind)
            else:
                parts.append('%s=%.2fs전 %dKB %dx%d' % (
                    kind, now - ent['ts'], len(ent['data']) // 1024,
                    ent['native_w'], ent['native_h']))
    return ' | '.join(parts)


if __name__ == '__main__':
    import sys
    sys.path.insert(0, '/home/oldmoon/workspace/linc-bot')
    start()
    start_reader_thread()
    print('수신 서버 대기 중 127.0.0.1:%d (Ctrl-C 종료)' % DEFAULT_PORT)
    ok = fail = 0
    try:
        while True:
            time.sleep(0.5)
            cur, mx = read_hp()
            if cur is None:
                fail += 1
            else:
                ok += 1
            total = ok + fail
            print('HP=%s/%s  성공률 %d/%d (%.1f%%)  %s' % (
                cur, mx, ok, total, 100.0 * ok / total if total else 0.0,
                status_text()))
    except KeyboardInterrupt:
        print('\n종료')
        stop()
