/*
 * LINC Vision Bridge - 콘텐츠 스크립트
 *
 * 목적: 게임 화면을 X11 화면캡처로 긁는 대신, WebRTC video 엘리먼트에서
 *       네이티브 해상도(1280x960) 픽셀을 직접 읽어 로컬 봇으로 보낸다.
 *
 * 이유(실측):
 *   - 화면캡처는 1280x960 원본을 1880x1410으로 확대한 결과를 다시 축소해서 읽으므로
 *     보간 얼룩 때문에 HP 숫자 OCR이 간헐적으로 실패했다.
 *   - 네이티브 픽셀로 읽으면 동일 OCR 함수가 scale 2/3/4/6 전부 정확히 읽었다.
 *   - HUD를 JPEG q70으로 보내면 244를 "294"로 오독한다(무성 오판 → 물약 미사용 사망).
 *     그래서 HUD는 반드시 PNG 무손실로 보낸다. 전체 프레임만 JPEG를 쓴다.
 */
(() => {
  'use strict';

  const SERVER = 'http://127.0.0.1:17311';

  // HUD 영역(네이티브 1280x960 기준). HP 숫자 y=763~778, 게이지 y=757~794,
  // LEV 박스 y=765~795 → 여유 있게 720~820을 통째로 무손실 전송한다.
  // 해상도가 1280x960이 아닐 수 있으므로 비율로 계산한다 (BTS: HUD 좌표 어긋남)
  const HUD_REF = { w: 1280, h: 960, x: 0, y: 720, cropH: 100 };
  function hudRect(v) {
    const vw = v.videoWidth, vh = v.videoHeight;
    return {
      x: 0,
      y: Math.round(vh * (HUD_REF.y / HUD_REF.h)),
      w: vw,
      h: Math.max(1, Math.round(vh * (HUD_REF.cropH / HUD_REF.h))),
    };
  }

  const HUD_INTERVAL_MS = 100;   // HP 감시는 촘촘히 (10fps)
  const FULL_INTERVAL_MS = 250;  // 몹 탐색용 전체 프레임 (4fps)
  const FULL_JPEG_QUALITY = 0.85; // q85 미만은 OCR 오독 위험 구간

  // ── HUD 게이지 판독기 (BTS-1033474, 사용자 지시 'HUD를 크롬익스텐션으로
  //    개발') ─────────────────────────────────────────────────────────────
  // 확장이 캡처만 하고 판독은 파이썬 OCR이던 구조를 확장 안 판독으로 바꾼다.
  // 근거(2026-09-15 실측): 게이지 채움 폭/트랙(272px)이 숫자 OCR 판독과
  // ±0.003 일치. 숫자 OCR은 '223'→'23' 오독으로 0.99를 0.09로 만들어 봇이
  // 'HP 위험 이탈'을 치는 사고가 났다. 게이지 폭은 자릿수 오독이 원천 없다.
  // 네이티브 1280 기준 값 — 스트립 폭 비율로 스케일 보정한다.
  const GAUGE_REF_W = 1280;
  const GAUGE_TRACK_PX = 272;     // 트랙 전체 폭(1280 기준 실측)
  const GAUGE_Y0 = 28, GAUGE_Y1 = 80;  // 게이지 밴드(스트립 y, 1280 기준)

  function hpRatioFromStrip(ctx, W, H) {
    const s = W / GAUGE_REF_W;    // x/y 공통 스케일(스트립은 1:1 크롭)
    const y0 = Math.max(0, Math.round(GAUGE_Y0 * s));
    const y1 = Math.min(H, Math.round(GAUGE_Y1 * s));
    const rows = y1 - y0, colsN = W;
    if (rows < 8) return null;
    const data = ctx.getImageData(0, y0, colsN, rows).data;
    // 빨강 HSV 마스크(V>=120, S>=0.58, H<=12 || H>=168) — 파이썬
    // inRange(0,150,120)..(10,255,255)|(170,..)와 동일 조건.
    const mask = new Uint8Array(colsN * rows);
    for (let y = 0; y < rows; y++) {
      for (let x = 0; x < colsN; x++) {
        const i = (y * colsN + x) * 4;
        const r = data[i], g = data[i + 1], b = data[i + 2];
        const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
        if (mx < 120 || mx === 0 || (mx - mn) / mx < 0.58) continue;
        const d = mx - mn;
        let h = 0;
        if (mx === r) h = 60 * ((((g - b) / d) % 6 + 6) % 6);
        else if (mx === g) h = 60 * ((b - r) / d + 2);
        else h = 60 * ((r - g) / d + 4);
        if (h <= 12 || h >= 168) mask[y * colsN + x] = 1;
      }
    }
    // 가로 3px dilate(파이썬 MORPH_CLOSE (1,3)의 근사 — bbox 좌우 1px
    // 부풀음은 모든 프레임에 동일하게 적용되어 ratio 비율 불변에 무해).
    const dil = new Uint8Array(colsN * rows);
    for (let y = 0; y < rows; y++) {
      const row = y * colsN;
      for (let x = 0; x < colsN; x++) {
        if (mask[row + x] || (x > 0 && mask[row + x - 1]) ||
            (x < colsN - 1 && mask[row + x + 1])) dil[row + x] = 1;
      }
    }
    // 4방향 연결요소 BFS → 막대 필터(최광폭) → 폭/트랙.
    const seen = new Uint8Array(colsN * rows);
    const queue = new Int32Array(colsN * rows);
    let bestW = 0;
    for (let start = 0; start < colsN * rows; start++) {
      if (!dil[start] || seen[start]) continue;
      let head = 0, tail = 0;
      queue[tail++] = start; seen[start] = 1;
      let minX = colsN, maxX = -1, minY = rows, maxY = -1;
      while (head < tail) {
        const p = queue[head++];
        const py = (p / colsN) | 0, px = p - py * colsN;
        if (px < minX) minX = px; if (px > maxX) maxX = px;
        if (py < minY) minY = py; if (py > maxY) maxY = py;
        if (px > 0 && dil[p - 1] && !seen[p - 1]) { seen[p - 1] = 1; queue[tail++] = p - 1; }
        if (px < colsN - 1 && dil[p + 1] && !seen[p + 1]) { seen[p + 1] = 1; queue[tail++] = p + 1; }
        if (py > 0 && dil[p - colsN] && !seen[p - colsN]) { seen[p - colsN] = 1; queue[tail++] = p - colsN; }
        if (py < rows - 1 && dil[p + colsN] && !seen[p + colsN]) { seen[p + colsN] = 1; queue[tail++] = p + colsN; }
      }
      const w = maxX - minX + 1, hh = maxY - minY + 1;
      if (w >= 30 * s && hh >= 15 * s && hh <= 35 * s &&
          w / hh <= 15 && w > bestW) bestW = w;
    }
    if (!bestW) return null;
    return Math.min(1.0, bestW / (GAUGE_TRACK_PX * s));
  }

  let video = null;
  let hudCanvas = null, hudCtx = null;
  let fullCanvas = null, fullCtx = null;

  let hudBusy = false, fullBusy = false;
  let lastHud = 0, lastFull = 0;

  // 서버가 죽어 있을 때 콘솔/네트워크를 도배하지 않도록 백오프
  let failStreak = 0;
  let mutedUntil = 0;

  function log(...a) { console.log('[linc-vision]', ...a); }

  function ensureCanvas(canvas, w, h) {
    if (!canvas) canvas = document.createElement('canvas');
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    return canvas;
  }

  function findVideo() {
    const list = document.querySelectorAll('video');
    for (const v of list) {
      if (v.videoWidth > 0 && v.videoHeight > 0) return v;
    }
    return null;
  }

  async function post(path, blob, headers) {
    const now = performance.now();
    if (now < mutedUntil) return false;
    try {
      await fetch(SERVER + path, { method: 'POST', body: blob, headers });
      if (failStreak > 0) log('수신 서버 복구됨');
      failStreak = 0;
      return true;
    } catch (e) {
      failStreak++;
      // 연속 실패하면 점점 뜸하게 재시도 (최대 5초)
      mutedUntil = now + Math.min(5000, 200 * failStreak);
      if (failStreak === 1) log('수신 서버 없음 → 백오프', e.message);
      return false;
    }
  }

  function blobOf(canvas, type, quality) {
    return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
  }

  async function sendHud(v) {
    if (hudBusy) return;
    hudBusy = true;
    try {
      const HUD = hudRect(v);
      hudCanvas = ensureCanvas(hudCanvas, HUD.w, HUD.h);
      if (!hudCtx) hudCtx = hudCanvas.getContext('2d', { willReadFrequently: true });
      // 네이티브 좌표에서 HUD 영역만 잘라 1:1로 그린다 (확대/축소 금지)
      hudCtx.drawImage(v, HUD.x, HUD.y, HUD.w, HUD.h, 0, 0, HUD.w, HUD.h);
      // 확장 안 판독(BTS-1033474): 게이지 채움 폭으로 HP 비율을 이 자리에서
      // 계산해 함께 보낸다. 파이썬 OCR은 이 값이 없을 때만 폴백으로 쓴다.
      let hpRatio = null;
      try { hpRatio = hpRatioFromStrip(hudCtx, HUD.w, HUD.h); }
      catch (e) { /* 판독 실패는 헤더 생략로 폴백 */ }
      const blob = await blobOf(hudCanvas, 'image/png');
      if (blob) {
        const headers = {
          'Content-Type': 'image/png',
          'X-Origin-X': String(HUD.x),
          'X-Origin-Y': String(HUD.y),
          'X-Native-W': String(v.videoWidth),
          'X-Native-H': String(v.videoHeight),
          'X-Ts': String(Date.now()),
        };
        if (hpRatio !== null && Number.isFinite(hpRatio)) {
          headers['X-HP-Ratio'] = hpRatio.toFixed(4);
        }
        await post('/hud', blob, headers);
      }
    } catch (e) {
      // 캔버스 오염(CORS) 등은 한 번만 알린다
      if (failStreak === 0) log('HUD 캡처 실패', e.message);
    } finally {
      hudBusy = false;
    }
  }

  async function sendFull(v) {
    if (fullBusy) return;
    fullBusy = true;
    try {
      fullCanvas = ensureCanvas(fullCanvas, v.videoWidth, v.videoHeight);
      if (!fullCtx) fullCtx = fullCanvas.getContext('2d');
      fullCtx.drawImage(v, 0, 0);
      const blob = await blobOf(fullCanvas, 'image/jpeg', FULL_JPEG_QUALITY);
      if (blob) {
        await post('/full', blob, {
          'Content-Type': 'image/jpeg',
          'X-Native-W': String(v.videoWidth),
          'X-Native-H': String(v.videoHeight),
          'X-Ts': String(Date.now()),
        });
      }
    } catch (e) {
      if (failStreak === 0) log('전체 프레임 캡처 실패', e.message);
    } finally {
      fullBusy = false;
    }
  }

  function tick() {
    if (!video || !video.videoWidth) {
      video = findVideo();
      if (!video) return;
      log('video 확보', video.videoWidth + 'x' + video.videoHeight);
    }
    const now = performance.now();
    if (now - lastHud >= HUD_INTERVAL_MS) { lastHud = now; sendHud(video); }
    if (now - lastFull >= FULL_INTERVAL_MS) { lastFull = now; sendFull(video); }
  }

  // 디코드된 프레임마다 호출되는 rVFC가 가장 정확하다.
  // 미지원 브라우저/비디오 교체 상황을 대비해 setInterval도 같이 돌린다(중복은 시간체크로 차단).
  function pump() {
    const v = video || findVideo();
    if (v && typeof v.requestVideoFrameCallback === 'function') {
      video = v;
      const cb = () => { tick(); try { v.requestVideoFrameCallback(cb); } catch (_) {} };
      try { v.requestVideoFrameCallback(cb); } catch (_) {}
    }
  }

  setInterval(tick, 50);
  setInterval(pump, 3000); // video 엘리먼트가 교체돼도 다시 붙는다
  pump();
  log('시작됨 (네이티브 프레임 브리지)');


  // ── 확장 HUD UI (BTS-1033569) ──
  // 게임 화면 왼쪽 하단에 봇 상태 패널. 클릭은 패널만 받고 게임은 가리지
  // 않게 접힌 채로 시작한다. 데이터는 ext_vision /hp.
  // 크롬 재시작 없이 CDP 재주입해도 이 함수가 기존 패널을 교체한다.
  function installHudUi() {
    if (window.__lincHudUiTimer) clearInterval(window.__lincHudUiTimer);
    document.querySelectorAll('#linc-bot-hud').forEach(e => e.remove());
    document.querySelectorAll('#linc-bot-hud-css').forEach(e => e.remove());

    const S = 'http://127.0.0.1:17311';
    // bot_settings.POTION_KINDS 와 동일. 등급: 맑은 > 주홍 > 빨간.
    const KIND_ORDER = ['맑은', '주홍', '빨간'];
    const KINDS = { '맑은': 30, '주홍': 20, '빨간': 6 };
    const KEYS = ['F1','F2','F3','F4','F5','F6','F7','F8','F9'];
    const sel = { key: 'F5', crisis: '', alt: 'F6', ret: 'F8' };
    let on = true;

    const css = document.createElement('style');
    css.id = 'linc-bot-hud-css';
    css.textContent = `
#linc-bot-hud{position:fixed;left:0;bottom:0;top:auto;right:auto;z-index:2147483647;
  background:linear-gradient(160deg,#181d28f2,#0c0f16f2);border:1px solid #3a465c;border-radius:16px;
  padding:14px 18px;color:#e8ecf4;font:20px/1.4 'Segoe UI',sans-serif;width:420px;max-width:96vw;
  max-height:82vh;overflow:auto;box-shadow:0 8px 32px rgba(0,0,0,.65);user-select:none}
#lb-head{display:flex;align-items:center;gap:10px;margin-bottom:8px}
#lb-title{font-weight:700;font-size:28px;letter-spacing:2px;color:#7ec8ff}
#lb-head button{width:34px;height:34px;border-radius:9px;border:1px solid #3a465c;background:#232b3a;color:#9fb4d8;font-size:18px;cursor:pointer}
#lb-head button:hover{background:#2e3950;color:#fff}
#lb-gear{margin-left:auto}
#lb-bar{width:100%;height:16px;background:#10131c;border-radius:9px;overflow:hidden;border:1px solid #000}
#lb-fill{height:100%;width:0;border-radius:9px;background:linear-gradient(90deg,#37d67a,#8ff5b3);transition:width .3s}
#lb-txt{font-size:48px;font-weight:700;margin-top:4px;line-height:1.1}
#lb-sub{color:#8d9cb8;font-size:16px;margin-top:2px}
#lb-opts{display:none;flex-direction:column;gap:10px;margin-top:10px;padding-top:12px;border-top:1px solid #2c3648}
#linc-bot-hud.open #lb-opts{display:flex}
.lb-sec{font-size:18px;font-weight:700;color:#7ec8ff;letter-spacing:1px}
.lb-row{display:flex;align-items:center;gap:10px}
.lb-row label{flex:1;color:#c3cdde;font-size:18px}
.lb-row .val{min-width:64px;text-align:right;font-weight:700;color:#fff;font-size:18px}
.lb-row select,.lb-row input[type=number]{font-size:20px;padding:6px 8px;background:#232b3a;color:#fff;
  border:1px solid #3a465c;border-radius:6px;min-width:120px;text-align:center}
.lb-keys{display:grid;grid-template-columns:repeat(10,1fr);gap:4px}
.lb-key{padding:8px 0;border-radius:7px;border:1px solid #3a465c;background:#232b3a;color:#9fb4d8;
  font:600 14px monospace;cursor:pointer;text-align:center}
.lb-key:hover{background:#2e3950}
.lb-key.sel{background:#2f6fc4;color:#fff;border-color:#7ec8ff}
.lb-toggle{position:relative;width:52px;height:26px;border-radius:13px;background:#2a3346;cursor:pointer;flex:none}
.lb-toggle.on{background:#2f9e5b}
.lb-toggle::after{content:'';position:absolute;top:3px;left:3px;width:20px;height:20px;border-radius:50%;background:#fff;transition:.2s}
.lb-toggle.on::after{left:29px}
#lb-save{margin-top:4px;padding:12px;border:0;border-radius:10px;background:linear-gradient(160deg,#2f6fc4,#2456a0);
  color:#fff;font-size:18px;font-weight:700;cursor:pointer}
#lb-msg{text-align:center;font-size:14px;color:#69d98d;min-height:16px}`;
    document.head.appendChild(css);

    const panel = document.createElement('div');
    panel.id = 'linc-bot-hud';
    panel.innerHTML = `
<div id="lb-head">
  <span id="lb-title">LINC BOT</span>
  <button id="lb-reset" title="왼쪽 하단으로">↺</button>
  <button id="lb-gear" title="설정">⚙</button>
</div>
<div id="lb-bar"><div id="lb-fill"></div></div>
<div id="lb-txt">HP --%</div>
<div id="lb-sub">설정은 ⚙</div>
<div id="lb-opts">
  <div class="lb-sec">물약</div>
  <div class="lb-row"><label>주 물약</label>
    <select id="st-kind-main"></select><span class="val" id="v-heal-main">+30%</span></div>
  <div class="lb-keys" id="lb-key-main"></div>
  <div class="lb-row"><label>위기 물약</label>
    <select id="st-kind-crisis"></select><span class="val" id="v-heal-crisis">-</span></div>
  <div class="lb-keys" id="lb-key-crisis"></div>
  <div class="lb-row"><label>보조 키</label></div>
  <div class="lb-keys" id="lb-key-alt"></div>
  <div class="lb-row"><label>시작</label>
    <input id="st-start" type="number" min="10" max="95" value="80"><span class="val">%</span></div>
  <div class="lb-row"><label>목표 회복</label>
    <input id="st-goal" type="number" min="10" max="99" value="80"><span class="val">%</span></div>
  <div class="lb-row"><label>연속 상한</label>
    <input id="st-chain" type="number" min="1" max="12" value="6"></div>
  <div class="lb-sec">비상 귀환</div>
  <div class="lb-row"><label>귀환 키</label></div>
  <div class="lb-keys" id="lb-key-return"></div>
  <div class="lb-row"><label>위험 임계</label>
    <input id="st-danger" type="number" min="1" max="40" value="20"><span class="val">%</span></div>
  <div class="lb-sec">전체</div>
  <div class="lb-row"><label>봇 활성</label><div class="lb-toggle on" id="st-on"></div></div>
  <button id="lb-save">저장</button>
  <div id="lb-msg"></div>
</div>`;
    document.body.appendChild(panel);

    const $ = id => document.getElementById(id);
    function healText(kind) {
      return kind && KINDS[kind] != null ? '+' + KINDS[kind] + '%' : '-';
    }
    function fillKinds(id, allowEmpty) {
      const el = $(id);
      if (!el) return;
      const opts = allowEmpty ? '<option value="">-</option>' : '';
      el.innerHTML = opts + KIND_ORDER.map(k => '<option value="'+k+'">'+k+'</option>').join('');
    }
    function paintGrid(elId, prop, allowEmpty) {
      const el = $(elId);
      if (!el) return;
      const cur = sel[prop];
      const none = allowEmpty
        ? '<div class="lb-key'+(cur===''?' sel':'')+'" data-k="">-</div>' : '';
      el.innerHTML = none + KEYS.map(k =>
        '<div class="lb-key'+(cur===k?' sel':'')+'" data-k="'+k+'">'+k+'</div>').join('');
      el.querySelectorAll('.lb-key').forEach(b => {
        b.onclick = () => {
          sel[prop] = b.dataset.k;
          el.querySelectorAll('.lb-key').forEach(x => x.classList.toggle('sel', x === b));
        };
      });
    }
    function paintAllGrids() {
      paintGrid('lb-key-main', 'key', false);
      paintGrid('lb-key-crisis', 'crisis', true);
      paintGrid('lb-key-alt', 'alt', false);
      paintGrid('lb-key-return', 'ret', false);
    }
    function inViewport(left, top, w, h) {
      return left >= 0 && top >= 0 && left < innerWidth - 80 && top < innerHeight - 80
        && top + Math.min(h, 80) > 0;
    }
    function placeDefault() {
      panel.style.top = 'auto';
      panel.style.right = 'auto';
      panel.style.bottom = '0px';
      panel.style.left = '0px';
      const v = document.querySelector('video');
      if (v && v.getBoundingClientRect) {
        const r = v.getBoundingClientRect();
        if (r.width > 100 && r.height > 100) {
          panel.style.left = Math.max(0, Math.round(r.left)) + 'px';
          panel.style.bottom = Math.max(0, Math.round(innerHeight - r.bottom)) + 'px';
        }
      }
    }
    function applySavedPos() {
      placeDefault();
      try {
        const saved = JSON.parse(localStorage.getItem('lincHudPos') || 'null');
        if (!saved || saved.l == null || saved.t == null) return;
        const left = parseInt(saved.l, 10), top = parseInt(saved.t, 10);
        if (!Number.isFinite(left) || !Number.isFinite(top) || !inViewport(left, top, 420, 80)) {
          localStorage.removeItem('lincHudPos');
          return;
        }
        panel.style.left = left + 'px';
        panel.style.top = top + 'px';
        panel.style.bottom = 'auto';
      } catch (_) {}
    }
    function makeDraggable() {
      const head = $('lb-head');
      if (!head) return;
      head.style.cursor = 'move';
      let sx=0, sy=0, ox=0, oy=0, moving=false;
      head.addEventListener('mousedown', e => {
        if (e.target && (e.target.id === 'lb-gear' || e.target.id === 'lb-reset')) return;
        moving = true; sx = e.clientX; sy = e.clientY;
        const r = panel.getBoundingClientRect(); ox = r.left; oy = r.top;
        panel.style.right = 'auto'; panel.style.bottom = 'auto';
        e.preventDefault();
      });
      window.addEventListener('mousemove', e => {
        if (!moving) return;
        const left = Math.max(0, Math.min(innerWidth - 80, ox + e.clientX - sx));
        const top = Math.max(0, Math.min(innerHeight - 80, oy + e.clientY - sy));
        panel.style.left = left + 'px';
        panel.style.top = top + 'px';
      });
      window.addEventListener('mouseup', () => {
        if (!moving) return; moving = false;
        try { localStorage.setItem('lincHudPos', JSON.stringify({l: panel.style.left, t: panel.style.top})); } catch (_) {}
      });
    }

    fillKinds('st-kind-main', false);
    fillKinds('st-kind-crisis', true);
    $('st-kind-main').value = '맑은';
    $('st-kind-main').onchange = () => { $('v-heal-main').textContent = healText($('st-kind-main').value); };
    $('st-kind-crisis').onchange = () => { $('v-heal-crisis').textContent = healText($('st-kind-crisis').value); };
    paintAllGrids();
    $('st-on').onclick = () => { on = !on; $('st-on').classList.toggle('on', on); };
    $('lb-gear').onclick = () => panel.classList.toggle('open');
    $('lb-reset').onclick = () => { try { localStorage.removeItem('lincHudPos'); } catch (_) {} placeDefault(); };

    async function loadSet() {
      try {
        const s = await (await fetch(S + '/bot-settings')).json();
        const mp = s.main_potion || {};
        const cp = s.crisis_potion || {};
        sel.key = mp.key || s.potion_key || sel.key;
        sel.crisis = cp.key || '';
        sel.alt = s.potion_key_alt || sel.alt;
        sel.ret = s.return_key || sel.ret;
        const kMain = KIND_ORDER.includes(mp.kind) ? mp.kind : '맑은';
        const kCrisis = KIND_ORDER.includes(cp.kind) ? cp.kind : '';
        $('st-kind-main').value = kMain;
        $('st-kind-crisis').value = kCrisis;
        $('v-heal-main').textContent = healText(kMain);
        $('v-heal-crisis').textContent = healText(kCrisis);
        $('st-start').value = s.potion_start_pct != null ? s.potion_start_pct : 80;
        $('st-goal').value = s.recover_to_pct != null ? s.recover_to_pct : 80;
        $('st-danger').value = s.danger_pct != null ? s.danger_pct : 20;
        $('st-chain').value = s.chain_max != null ? s.chain_max : 6;
        on = s.enabled !== false;
        $('st-on').classList.toggle('on', on);
        paintAllGrids();
      } catch (e) {
        console.log('[linc-hud] settings load fail', e && e.message);
      }
    }
    $('lb-save').onclick = async () => {
      const kMain = $('st-kind-main').value || '맑은';
      const kCrisis = $('st-kind-crisis').value || '';
      const body = {
        main_potion: { key: sel.key, kind: kMain, heal_pct: KINDS[kMain] || 30 },
        crisis_potion: { key: sel.crisis, kind: kCrisis, heal_pct: KINDS[kCrisis] || 0 },
        potion_key: sel.key,
        orange_key: sel.key,
        potion_key_alt: sel.alt,
        return_key: sel.ret,
        potion_start_pct: +$('st-start').value,
        recover_to_pct: +$('st-goal').value,
        danger_pct: +$('st-danger').value,
        chain_max: +$('st-chain').value,
        enabled: on
      };
      try {
        await fetch(S + '/bot-settings', { method: 'POST',
          headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
        $('lb-msg').textContent = '저장됨';
        setTimeout(() => { $('lb-msg').textContent = ''; }, 2000);
      } catch (e) { $('lb-msg').textContent = '저장 실패'; }
    };
    async function poll() {
      try {
        const r = await (await fetch(S + '/hp?scale=4')).json();
        let hp = null;
        if (r.hp != null && r.hp_max) hp = r.hp / r.hp_max;
        else if (r.bot && r.bot.ratio != null) hp = r.bot.ratio;
        else if (typeof r.ratio === 'number') hp = r.ratio;
        if (hp != null && Number.isFinite(hp)) {
          hp = Math.max(0, Math.min(1, hp));
          $('lb-fill').style.width = Math.round(hp * 100) + '%';
          $('lb-fill').style.background = hp < 0.45
            ? 'linear-gradient(90deg,#e5484d,#ff8a8a)'
            : hp < 0.8 ? 'linear-gradient(90deg,#f5b431,#ffd76e)'
            : 'linear-gradient(90deg,#37d67a,#8ff5b3)';
          $('lb-txt').textContent = 'HP ' + Math.round(hp * 100) + '%';
        }
        $('lb-sub').textContent = r.bot
          ? ('사냥 ' + (r.bot.kills || 0) + '회')
          : (panel.classList.contains('open') ? '설정 가능' : '설정은 ⚙');
      } catch (e) {
        $('lb-sub').textContent = '수신 없음';
      }
    }

    applySavedPos();
    makeDraggable();
    window.__lincHudUiTimer = setInterval(poll, 400);
    poll();
    loadSet();
    return 'ui-v4';
  }
  installHudUi();
})();
