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


  // ── 확장 HUD UI(BTS-1033474 계열, 사용자 지시 '크롬 익스텐션 UI') ──
  // 게임 화면 좌상단에 봇 상태 패널을 띄운다. pointer-events:none 이므로
  // 게임 조작을 절대 가로채지 않는다. 데이터는 ext_vision /hp(봇 게시값
  // 우선). 이 파일은 크롬 재시작 시점부터 상주한다(그 전엔 페이지 주입본
  // 이 동일 UI를 제공).
  function installHudUi() {

  if (window.__lincHudUiTimer) clearInterval(window.__lincHudUiTimer);
  document.querySelectorAll('#linc-bot-hud').forEach(e => e.remove());
  const S = 'http://127.0.0.1:17311';
  const css = document.createElement('style');
  css.textContent = `
#linc-bot-hud *{box-sizing:border-box}
#linc-bot-hud{position:fixed;z-index:2147483647;
  background:linear-gradient(175deg,#16294f 0%,#0b1730 55%,#081026 100%);
  border:2px solid #8a6a2f;border-radius:0 10px 0 0;padding:14px 18px 16px 20px;
  color:#e8e0c8;font:14px/1.55 'Gulim','Malgun Gothic',sans-serif;
  min-width:340px;box-shadow:0 0 0 1px #3a2c10,0 10px 34px rgba(0,0,0,.75),inset 0 0 22px rgba(0,10,40,.55);user-select:none}
#linc-bot-hud::before{content:'';position:absolute;left:6px;top:8px;bottom:8px;width:5px;
  background:linear-gradient(#e0a94f,#8a6a2f 60%,#c89b4a);border-radius:2px}
#lb-head{display:flex;align-items:center;gap:10px;margin-bottom:10px}
#lb-title{font-weight:700;font-size:18px;letter-spacing:3px;color:#f0c96a;text-shadow:0 1px 2px #000}
#lb-gear{margin-left:auto;width:32px;height:32px;border-radius:3px;border:1px solid #8a6a2f;background:#101d3a;color:#e0a94f;font-size:17px;cursor:pointer;transition:.15s}
#lb-gear:hover{background:#1c2f5e;color:#ffe9a8}
#lb-bar{width:100%;height:18px;background:#060d1e;border-radius:2px;overflow:hidden;border:1px solid #3a2c10}
#lb-fill{height:100%;width:0%;border-radius:9px;background:linear-gradient(90deg,#37d67a,#8ff5b3);transition:width .3s}
#lb-txt{font-size:24px;font-weight:700;margin-top:6px}
#lb-sub{color:#8d9cb8;font-size:13px;margin-top:2px}
#lb-opts{display:none;flex-direction:column;gap:12px;margin-top:12px;padding-top:14px;border-top:1px solid #2c3648}
#linc-bot-hud.open #lb-opts{display:flex}
.lb-sec{font-size:12px;font-weight:700;color:#d8b25e;letter-spacing:2px;margin-bottom:-4px;border-bottom:1px solid #3a2c10;padding-bottom:3px}
.lb-row{display:flex;align-items:center;gap:10px}
.lb-row label{flex:1;color:#c3cdde;font-size:14px}
.lb-row .val{min-width:48px;text-align:right;font-weight:700;color:#fff}
.lb-slider{flex:1.4;appearance:none;height:6px;border-radius:2px;background:#0a142c;border:1px solid #3a2c10;outline:none}
.lb-slider::-webkit-slider-thumb{appearance:none;width:16px;height:16px;border-radius:2px;background:#e0a94f;border:1px solid #6a5218;cursor:pointer}
.lb-keys{display:grid;grid-template-columns:repeat(9,1fr);gap:4px}
.lb-key{padding:6px 0;border-radius:3px;border:1px solid #5a4718;background:#101d3a;color:#cabb8e;font:600 13px monospace;cursor:pointer;text-align:center;transition:.12s}
.lb-key:hover{background:#1c2f5e;border-color:#c89b4a}
.lb-key.sel{background:#5a3f12;color:#ffe9a8;border-color:#e0a94f;box-shadow:0 0 7px #c89b4a99}
.lb-toggle{position:relative;width:52px;height:24px;border-radius:3px;background:#0a142c;border:1px solid #5a4718;cursor:pointer;transition:.2s;flex:none}
.lb-toggle.on{background:#7a5a18}
.lb-toggle::after{content:'';position:absolute;top:3px;left:3px;width:20px;height:20px;border-radius:50%;background:#fff;transition:.2s}
.lb-toggle.on::after{left:29px}
#lb-stepper{display:flex;align-items:center;gap:8px}
#lb-stepper button{width:30px;height:30px;border-radius:8px;border:1px solid #3a465c;background:#232b3a;color:#fff;font-size:17px;cursor:pointer}
#lb-save{margin-top:4px;padding:10px;border:1px solid #e0a94f;border-radius:3px;background:linear-gradient(#3a2c10,#241a06);color:#ffe9a8;font-size:15px;font-weight:700;cursor:pointer;letter-spacing:6px}
#lb-save:hover{background:linear-gradient(#5a3f12,#3a2c10)}
#lb-msg{text-align:center;font-size:13px;color:#69d98d;min-height:16px}`;
  document.head.appendChild(css);
  const panel = document.createElement('div');
  panel.id = 'linc-bot-hud';
  panel.classList.add('open');
  panel.innerHTML = `
<div id="lb-head"><span id="lb-title">LINC BOT</span><button id="lb-gear" title="설정">⚙</button></div>
<div id="lb-bar"><div id="lb-fill"></div></div>
<div id="lb-txt">HP --%</div>
<div id="lb-sub">초기화...</div>
<div id="lb-opts">
  <div class="lb-sec">🧪 물약</div>
  <div class="lb-row"><label>주 물약</label><select id="st-kind1" style="font-size:13px;padding:2px 6px;background:#101d3a;color:#ffe9a8;border:1px solid #8a6a2f"></select><span class="val" id="v-heal1">+8%</span></div>
  <div class="lb-keys" id="lb-key1"></div>
  <div class="lb-row" style="margin-top:6px"><label>위기 물약(&lt;45%)</label><select id="st-kind2" style="font-size:13px;padding:2px 6px;background:#101d3a;color:#ffe9a8;border:1px solid #8a6a2f"></select><span class="val" id="v-heal2">-</span></div>
  <div class="lb-keys" id="lb-key2"></div>
  <div class="lb-row" style="margin-top:6px"><label>보조 키</label></div>
  <div class="lb-keys" id="lb-key2"></div>
  <div class="lb-row"><label>시작</label><input class="lb-slider" id="st-start" type="range" min="10" max="95"><span class="val" id="v-start">80%</span></div>
  <div class="lb-row"><label>목표 회복</label><input class="lb-slider" id="st-goal" type="range" min="10" max="99"><span class="val" id="v-goal">80%</span></div>
  <div class="lb-row"><label>연속 상한</label><div id="lb-stepper"><button id="st-chminus">−</button><span class="val" id="v-chain">6</span><button id="st-chplus">＋</button></div></div>
  <div class="lb-sec">🌀 비상 귀환</div>
  <div class="lb-row"><label>귀환 키(F8 주문서)</label></div>
  <div class="lb-keys" id="lb-key3"></div>
  <div class="lb-row"><label>위험 임계</label><input class="lb-slider" id="st-danger" type="range" min="1" max="40"><span class="val" id="v-danger">20%</span></div>
  <div class="lb-sec">전체</div>
  <div class="lb-row"><label>봇 활성</label><div class="lb-toggle on" id="st-on"></div></div>
  <button id="lb-save">저 장</button>
  <div id="lb-msg"></div>
</div>`;
  document.body.appendChild(panel);
  const $ = id => document.getElementById(id);
  const KINDS = {'초록':6,'맑은':8,'주홍':12,'붉은':18,'진홍':24};
  function fillKinds(id, healId) {
    const el = $(id); el.innerHTML = '<option value="">-</option>' +
      Object.keys(KINDS).map(k => `<option value="${k}">${k}</option>`).join('');
    el.onchange = () => { $(healId).textContent = el.value ? '+' + KINDS[el.value] + '%' : '-'; };
  }
  const KEYS = [...Array(9)].map((_, i) => 'F' + (i + 1));
  const sel = { key: 'F6', alt: 'F5', ret: 'F8', red: '', green: '' };

  function gridX(elId, prop) {
    const el = $(elId);
    const none = document.createElement('div');
    none.className = 'lb-key' + (sel[prop] === '' ? ' sel' : '');
    none.textContent = ' - ';
    none.onclick = () => { sel[prop] = ''; el.querySelectorAll('.lb-key').forEach(x => x.classList.toggle('sel', x === none)); };
    el.appendChild(none);
    KEYS.forEach(k => {
      const b = document.createElement('div');
      b.className = 'lb-key' + (sel[prop] === k ? ' sel' : '');
      b.textContent = k;
      b.onclick = () => { sel[prop] = k; el.querySelectorAll('.lb-key').forEach(x => x.classList.toggle('sel', x === b)); };
      el.appendChild(b);
    });
  }
  function grid(elId, prop) {
    const el = $(elId);
    el.innerHTML = KEYS.map(k => `<div class="lb-key${sel[prop]===k?' sel':''}" data-k="${k}">${k}</div>`).join('');
    el.querySelectorAll('.lb-key').forEach(b => b.onclick = () => {
      sel[prop] = b.dataset.k;
      el.querySelectorAll('.lb-key').forEach(x => x.classList.toggle('sel', x === b));
    });
  }
  function bindSlider(id, vid, suffix='%') {
    $(id).oninput = () => $(vid).textContent = $(id).value + suffix;
  }
  bindSlider('st-start', 'v-start'); bindSlider('st-goal', 'v-goal'); bindSlider('st-danger', 'v-danger');
  let chain = 6;
  $('st-chminus').onclick = () => { chain = Math.max(1, chain - 1); $('v-chain').textContent = chain; };
  $('st-chplus').onclick = () => { chain = Math.min(8, chain + 1); $('v-chain').textContent = chain; };
  let on = true;
  $('st-on').onclick = () => { on = !on; $('st-on').classList.toggle('on', on); };
  $('lb-gear').onclick = () => panel.classList.toggle('open');
  fillKinds('st-kind1', 'v-heal1'); fillKinds('st-kind2', 'v-heal2');
  async function loadSet() {
    try { const s = await (await fetch(S + '/bot-settings')).json();
      sel.key = s.orange_key || s.potion_key; sel.alt = s.potion_key_alt; sel.ret = s.return_key; sel.red = s.red_key || ''; sel.green = s.green_key || '';
      const mp = s.main_potion || {}, cp = s.crisis_potion || {};
      sel.kind1 = mp.kind || '맑은'; sel.kind2 = cp.kind || '';
      sel.ckey = cp.key || '';
      $('st-kind1').value = sel.kind1; $('st-kind2').value = sel.kind2;
      $('v-heal1').textContent = '+' + (mp.heal_pct || 8) + '%';
      $('v-heal2').textContent = sel.kind2 ? '+' + (cp.heal_pct || 12) + '%' : '-';
      const csel = document.querySelector('#lb-key2 .lb-key.sel');
      if (sel.ckey && !csel) { document.querySelectorAll('#lb-key2 .lb-key').forEach(x => { if (x.textContent === sel.ckey) x.classList.add('sel'); }); }
      grid('lb-key1', 'key'); grid('lb-key2', 'alt'); grid('lb-key3', 'ret'); gridX('lb-keyr', 'red'); gridX('lb-keyg', 'green');
      $('st-start').value = s.potion_start_pct; $('v-start').textContent = s.potion_start_pct + '%';
      $('st-goal').value = s.recover_to_pct; $('v-goal').textContent = s.recover_to_pct + '%';
      $('st-danger').value = s.danger_pct; $('v-danger').textContent = s.danger_pct + '%';
      chain = s.chain_max; $('v-chain').textContent = chain;
      on = s.enabled; $('st-on').classList.toggle('on', on);
    } catch (e) {}
  }
  $('lb-save').onclick = async () => {
    try {
      const heal1 = KINDS[$('st-kind1').value] || 8;
      const heal2 = KINDS[$('st-kind2').value] || 0;
      const ckey = document.querySelector('#lb-key2 .lb-key.sel')?.textContent || '';
      const body = { main_potion: {key: sel.key, kind: $('st-kind1').value, heal_pct: heal1},
        crisis_potion: {key: ckey, kind: $('st-kind2').value, heal_pct: heal2},
        potion_key: sel.key, potion_key_alt: sel.alt, return_key: sel.ret,
        potion_start_pct: +$('st-start').value, recover_to_pct: +$('st-goal').value,
        danger_pct: +$('st-danger').value, chain_max: chain, enabled: on };
      await fetch(S + '/bot-settings', { method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
      $('lb-msg').textContent = '저장됨 — 즉시 반영 ✓';
      setTimeout(() => $('lb-msg').textContent = '', 2200);
    } catch (e) { $('lb-msg').textContent = '저장 실패'; }
  };
  function anchorToGame() {
    // 사용자 지시(2026-09-15): '게임실행밑으로' — 게임 실행(비디오)
    // 아래쪽에 배치. left=게임 화면 시작 x, bottom=브라우저 맨밑.
    const p = document.getElementById('linc-bot-hud');
    if (!p) return;
    const v = document.querySelector('video');
    const vw = v ? v.getBoundingClientRect() : {left: 0, width: innerWidth};
    p.style.left = Math.max(0, Math.round(vw.left + vw.width / 2 - p.offsetWidth / 2)) + 'px';
    p.style.bottom = '0px';
  }

  function makeDraggable() {
    // 사용자가 직접 위치를 잡는다(2026-09-16): 헤더(제목/⚙ 영역)를
    // 드래그하면 패널이 따라오고, 놓은 위치가 localStorage에 저장돼
    // 새로고침/재주입 후에도 유지된다. 앵커(자동 배치)보다 우선.
    const p = document.getElementById('linc-bot-hud');
    const head = document.getElementById('lb-head');
    if (!p || !head) return;
    let sx = 0, sy = 0, ox = 0, oy = 0, moving = false;
    head.style.cursor = 'move';
    head.addEventListener('mousedown', e => {
      if (e.target.id === 'lb-gear') return;
      moving = true; sx = e.clientX; sy = e.clientY;
      const r = p.getBoundingClientRect(); ox = r.left; oy = r.top;
      p.style.right = 'auto'; p.style.bottom = 'auto';
      e.preventDefault();
    });
    window.addEventListener('mousemove', e => {
      if (!moving) return;
      p.style.left = Math.max(0, ox + e.clientX - sx) + 'px';
      p.style.top = Math.max(0, oy + e.clientY - sy) + 'px';
    });
    window.addEventListener('mouseup', () => {
      if (!moving) return; moving = false;
      try { localStorage.setItem('lincHudPos', JSON.stringify({l: p.style.left, t: p.style.top})); } catch (_) {}
    });
    try {
      const saved = JSON.parse(localStorage.getItem('lincHudPos') || 'null');
      if (saved && saved.l && saved.t) { p.style.left = saved.l; p.style.top = saved.t; p.style.right = 'auto'; p.style.bottom = 'auto'; }
    } catch (_) {}
  }
  async function poll() {
    if (!localStorage.getItem('lincHudPos')) anchorToGame();
    try {
      const r = await (await fetch(S + '/hp?scale=4')).json();
      let hp = (r.hp != null && r.hp_max && r.hp > 0) ? r.hp / r.hp_max :
               (r.bot && r.bot.ratio != null) ? r.bot.ratio :
               (r.ratio != null && r.ratio !== false) ? r.ratio : null;
      if (hp != null && (hp < 0.15 || (window.__lbLast != null && window.__lbLast > 0.5 && hp < window.__lbLast - 0.4))) hp = null;  // 저값/급낙 오독 — 이전 표시 유지
      if (hp != null) {
        $('lb-fill').style.width = Math.round(hp * 100) + '%';
        $('lb-fill').style.background = hp < 0.45 ? 'linear-gradient(90deg,#e5484d,#ff8a8a)'
          : hp < 0.8 ? 'linear-gradient(90deg,#f5b431,#ffd76e)'
          : 'linear-gradient(90deg,#37d67a,#8ff5b3)';
        window.__lbLast = hp;
        $('lb-txt').textContent = 'HP ' + Math.round(hp * 100) + '%';
      }
      $('lb-sub').textContent = r.bot ? ('사냥 ' + (r.bot.kills || 0) + '회 · 봇 판독') : '봇 대기 중';
    } catch (e) { $('lb-sub').textContent = '수신 없음'; }
  }
  makeDraggable();
  window.__lincHudUiTimer = setInterval(poll, 50);
  poll(); loadSet();
  return 'ui-v3';
}
installHudUi();
})();
