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

  const HUD_INTERVAL_MS = 50;    // HP 동기화 50ms (사용자 지시)
  const HUD_PNG_INTERVAL_MS = 200; // OCR 폴백용 PNG는 덜 자주
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

  let hudBusy = false, fullBusy = false, ratioBusy = false, pngBusy = false;
  let lastHud = 0, lastFull = 0, lastPng = 0;

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
    let hpRatio = null;
    try {
      const HUD = hudRect(v);
      hudCanvas = ensureCanvas(hudCanvas, HUD.w, HUD.h);
      if (!hudCtx) hudCtx = hudCanvas.getContext('2d', { willReadFrequently: true });
      hudCtx.drawImage(v, HUD.x, HUD.y, HUD.w, HUD.h, 0, 0, HUD.w, HUD.h);
      try { hpRatio = hpRatioFromStrip(hudCtx, HUD.w, HUD.h); }
      catch (e) { /* 판독 실패는 헤더 생략로 폴백 */ }
      if (hpRatio !== null && Number.isFinite(hpRatio) && !ratioBusy) {
        ratioBusy = true;
        fetch(SERVER + '/ext-ratio', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ratio: hpRatio, ts: Date.now() }),
        }).catch(() => {}).finally(() => { ratioBusy = false; });
      }
    } catch (e) {
      if (failStreak === 0) log('HUD 캡처 실패', e.message);
    } finally {
      hudBusy = false;
    }
    const now = performance.now();
    if (pngBusy || now - lastPng < HUD_PNG_INTERVAL_MS) return;
    lastPng = now;
    pngBusy = true;
    try {
      const blob = await blobOf(hudCanvas, 'image/png');
      if (blob) {
        const HUD = hudRect(v);
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
      if (failStreak === 0) log('HUD PNG 전송 실패', e.message);
    } finally {
      pngBusy = false;
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
    if (window.__lincHudMountTimer) clearInterval(window.__lincHudMountTimer);
    document.querySelectorAll('#linc-hud,#linc-bot-hud,#linc-hud-slot,#linc-hud-css,#linc-bot-hud-css').forEach(e => e.remove());
    document.querySelectorAll('style').forEach(e => {
      if (e.textContent && (e.textContent.indexOf('#linc-hud') >= 0 || e.textContent.indexOf('#linc-bot-hud') >= 0)) e.remove();
    });

    const S = 'http://127.0.0.1:17311';
    const KEYS = ['F1','F2','F3','F4','F5','F6','F7','F8','F9'];
    const POTIONS = {
      '빨간': { name:'빨간 물약', officialName:'체력 회복제', healMin:6, healMax:27, healAverage:16.5 },
      '주홍': { name:'주홍 물약', officialName:'고급 체력 회복제', healMin:26, healMax:68, healAverage:47 },
      '맑은': { name:'맑은 물약', officialName:'강력 체력 회복제', healMin:44, healMax:107, healAverage:75.5 }
    };
    const KIND_ORDER = ['주홍', '맑은', '빨간'];
    const sel = {
      main:'F5', emg:'F6', fb:'F4', ret:'F8',
      buff1:'', buff2:'F9', shape:'F3', anti:'F2'
    };
    let CLASS_CONFIG = {};
    let CLASSES = [
      {id:'prince', name:'군주'}, {id:'knight', name:'기사'},
      {id:'elf', name:'요정'}, {id:'wizard', name:'마법사'}
    ];
    let WEAPONS = [
      {id:'sword1h', name:'한손검'}, {id:'sword2h', name:'양손검'},
      {id:'bow', name:'활'}, {id:'spear', name:'창'},
      {id:'staff', name:'지팡이'}, {id:'dagger', name:'단검'}, {id:'other', name:'기타'}
    ];
    let TRANSFORMS = [];
    let classProfiles = {};
    let tFav = [];
    let tHist = [];
    let tTab = 'recent';
    let preferredId = 'orc_scout';
    let fallbackId = 'skeleton_archer';
    let charClass = 'knight';
    const buffOn = {};
    const buffKey = {};
    let MP_POTIONS = [{id:'', name:'-'}, {id:'mana', name:'마력 회복제'}, {id:'mana_hi', name:'고급 마력 회복제'}, {id:'mana_strong', name:'강력 마력 회복제'}];
    let FUNC_CATALOG = [];
    let SKILLS = {};
    let funcItems = [];
    let attackSkills = [];
    let buffRemain = {};
    sel.mp1 = '';
    sel.mp2 = '';

    const css = document.createElement('style');
    css.id = 'linc-hud-css';
    css.textContent = `
#linc-hud-slot{width:100%;max-width:100%;min-width:0;box-sizing:border-box;margin-top:12px;flex:1 1 auto;min-height:0;overflow-x:hidden;overflow-y:auto}
#linc-hud{
  --linc-padding:14px;--linc-gap-xs:4px;--linc-gap-sm:6px;--linc-gap-md:10px;--linc-gap-lg:14px;
  --linc-font-caption:11px;--linc-font-small:12px;--linc-font-normal:13px;--linc-font-section:16px;
  --linc-font-title:24px;--linc-font-hp:38px;--linc-control-height:30px;
  --linc-radius-sm:5px;--linc-radius-md:8px;--linc-radius-panel:12px;
  --linc-bg:#151a23;--linc-control-bg:#202938;--linc-border:#344155;
  --linc-text:#e8edf5;--linc-muted:#93a0b2;--linc-accent:#49a7ff;--linc-active:#287bd4;--linc-on:#28ae68;
  width:100%;max-width:100%;min-width:0;box-sizing:border-box;
  position:relative;left:auto;right:auto;top:auto;bottom:auto;
  background:var(--linc-bg);border:1px solid var(--linc-border);border-radius:var(--linc-radius-panel);
  padding:var(--linc-padding);color:var(--linc-text);font:var(--linc-font-normal)/1.4 'Segoe UI',sans-serif;
  overflow-x:hidden;user-select:none}
#linc-hud *{box-sizing:border-box;max-width:100%}
.lh-head{display:flex;align-items:center;gap:8px;margin-bottom:8px}
#lh-title{font-weight:700;font-size:var(--linc-font-title);letter-spacing:1px;color:var(--linc-accent)}
#lh-gear{margin-left:auto;width:30px;height:30px;border-radius:var(--linc-radius-sm);border:1px solid var(--linc-border);background:var(--linc-control-bg);color:var(--linc-muted);cursor:default}
#lh-bar{width:100%;height:10px;background:#10131c;border-radius:6px;overflow:hidden;border:1px solid #000}
#lh-fill{height:100%;width:0;background:linear-gradient(90deg,#37d67a,#8ff5b3)}
#lh-hp{font-size:var(--linc-font-hp);font-weight:700;line-height:1.1;margin-top:4px}
#lh-mp{font-size:22px;font-weight:700;line-height:1.1;margin-top:2px}
#linc-hud.wizard #lh-mp{font-size:28px}
#lh-sub{color:var(--linc-muted);font-size:var(--linc-font-caption);margin-top:2px}
.lh-tabs{display:flex;gap:4px;margin:6px 0}
.lh-tab{flex:1;height:26px;border:1px solid var(--linc-border);background:var(--linc-control-bg);color:var(--linc-muted);border-radius:5px;font-size:11px;cursor:pointer}
.lh-tab.on{background:var(--linc-active);color:#fff;border-color:var(--linc-accent)}
.lh-tlist{max-height:160px;overflow-y:auto;overflow-x:hidden;border:1px solid var(--linc-border);border-radius:6px}
.lh-titem{display:flex;align-items:center;gap:6px;padding:5px 8px;font-size:12px;cursor:pointer;border-bottom:1px solid #1c2430}
.lh-titem.sel{background:#1e2a3d}
.lh-star{width:22px;height:22px;border:0;background:transparent;color:#8a94a6;cursor:pointer;font-size:14px}
.lh-star.on{color:#f5c542}
#st-tsearch{width:100%;height:28px;margin:4px 0;background:var(--linc-control-bg);color:var(--linc-text);border:1px solid var(--linc-border);border-radius:5px;padding:0 8px;font-size:12px}
#lh-warn{color:#ff8a8a;font-size:var(--linc-font-caption);min-height:14px;margin-top:4px}
.lh-sec{font-size:var(--linc-font-section);font-weight:700;color:var(--linc-accent);margin:var(--linc-gap-lg) 0 var(--linc-gap-sm);padding-top:var(--linc-gap-md);border-top:1px solid var(--linc-border)}
.lh-row{display:flex;align-items:center;gap:var(--linc-gap-sm);margin:var(--linc-gap-sm) 0;min-width:0}
.lh-row label{flex:1;color:var(--linc-text);font-size:var(--linc-font-normal);min-width:0}
.lh-note{color:var(--linc-muted);font-size:var(--linc-font-caption);margin:2px 0 6px}
.lh-row select,.lh-row input[type=number]{height:var(--linc-control-height);background:var(--linc-control-bg);color:var(--linc-text);border:1px solid var(--linc-border);border-radius:var(--linc-radius-sm);font-size:var(--linc-font-normal);text-align:center}
.lh-row input[type=number]{width:60px;flex:none}
.lh-row select{min-width:0;flex:1.2}
.lh-keys{display:flex;flex-wrap:wrap;gap:var(--linc-gap-xs);margin:4px 0 8px}
.lh-key{width:30px;height:30px;border-radius:var(--linc-radius-sm);border:1px solid var(--linc-border);background:var(--linc-control-bg);color:var(--linc-muted);font:600 11px monospace;cursor:pointer;display:flex;align-items:center;justify-content:center}
.lh-key.sel{background:var(--linc-active);color:#fff;border-color:var(--linc-accent)}
.lh-tog{position:relative;width:40px;height:22px;border-radius:11px;background:#2a3346;cursor:pointer;flex:none}
.lh-tog.on{background:var(--linc-on)}
.lh-tog::after{content:'';position:absolute;top:3px;left:3px;width:16px;height:16px;border-radius:50%;background:#fff;transition:.15s}
.lh-tog.on::after{left:21px}
#lh-save{display:block;width:100%;height:40px;margin-top:var(--linc-gap-lg);border:0;border-radius:var(--linc-radius-md);background:var(--linc-active);color:#fff;font-size:var(--linc-font-small);font-weight:700;cursor:pointer}
#lh-msg{text-align:center;font-size:var(--linc-font-caption);color:var(--linc-on);min-height:14px;margin-top:4px}`;
    document.head.appendChild(css);

    const panel = document.createElement('div');
    panel.id = 'linc-hud';
    panel.className = 'linc-hud';
    panel.innerHTML = `
<div class="lh-head"><span id="lh-title">LINC-HUD</span><button id="lh-gear" title="설정">⚙</button></div>
<div id="lh-bar"><div id="lh-fill"></div></div>
<div id="lh-hp">HP --%</div>
<div id="lh-mp">MP --%</div>
<div id="lh-sub">봇 대기 중</div>
<div id="lh-warn"></div>
<div class="lh-sec">캐릭터</div>
<div class="lh-row"><label>클래스</label><select id="st-class"></select></div>
<div class="lh-row"><label>레벨</label><input id="st-level" type="number" min="1" max="99" value="27"></div>
<div class="lh-row"><label>무기</label><select id="st-weapon"></select></div>
<div class="lh-sec">💉 HP 회복</div>
<div class="lh-row"><label>1차 물약</label><select id="st-kind-main"></select></div>
<div class="lh-note" id="note-main"></div>
<div class="lh-row"><label>HP ≤</label><input id="st-hp-main" type="number" min="10" max="95" value="80"><span class="lh-note">%</span></div>
<div class="lh-keys" id="lh-key-main"></div>
<div class="lh-row"><label>2차 물약</label><select id="st-kind-emg"></select></div>
<div class="lh-note" id="note-emg"></div>
<div class="lh-row"><label>HP ≤</label><input id="st-hp-emg" type="number" min="5" max="80" value="45"><span class="lh-note">%</span></div>
<div class="lh-keys" id="lh-key-emg"></div>
<div class="lh-row"><label>주 물약 소진 시 대체 물약 사용</label><div class="lh-tog on" id="st-fallback"></div></div>
<div class="lh-row"><label>대체 물약</label><select id="st-kind-fb"></select></div>
<div class="lh-keys" id="lh-key-fb"></div>
<div class="lh-sec">🌀 안전</div>
<div class="lh-row"><label>비상 귀환</label><div class="lh-tog on" id="st-return"></div></div>
<div class="lh-row"><label>위험 HP ≤</label><input id="st-danger" type="number" min="1" max="40" value="20"><span class="lh-note">%</span></div>
<div class="lh-keys" id="lh-key-return"></div>
<div class="lh-row"><label>물약 없음 귀환</label><div class="lh-tog on" id="st-empty-return"></div></div>
<div class="lh-row"><label>무게 귀환</label><div class="lh-tog on" id="st-weight-return"></div></div>
<div class="lh-row"><label>무게 ≥</label><input id="st-weight-pct" type="number" min="50" max="99" value="80"><span class="lh-note">%</span></div>
<div class="lh-row"><label>MP 귀환</label><div class="lh-tog" id="st-mp-return"></div></div>
<div class="lh-row"><label>MP ≤</label><input id="st-mp-ret" type="number" min="1" max="50" value="10"><span class="lh-note">%</span></div>
<div class="lh-row"><label>비전투 귀환</label><div class="lh-tog" id="st-idle-return"></div></div>
<div class="lh-row"><label>전투 없음</label><input id="st-idle-sec" type="number" min="30" max="3600" value="600"><span class="lh-note">초</span></div>
<div class="lh-sec">💙 MP 회복</div>
<div class="lh-row"><label>MP 회복</label><div class="lh-tog" id="st-mp-on"></div></div>
<div class="lh-row"><label>1차 MP</label><select id="st-mp1"></select></div>
<div class="lh-row"><label>MP ≤</label><input id="st-mp1-pct" type="number" min="5" max="90" value="30"><span class="lh-note">%</span></div>
<div class="lh-keys" id="lh-key-mp1"></div>
<div class="lh-row"><label>2차 MP</label><select id="st-mp2"></select></div>
<div class="lh-row"><label>MP ≤</label><input id="st-mp2-pct" type="number" min="1" max="50" value="15"><span class="lh-note">%</span></div>
<div class="lh-keys" id="lh-key-mp2"></div>
<div class="lh-sec">🎁 아이템</div>
<div class="lh-row"><label>아이템 줍기</label><div class="lh-tog on" id="st-pickup"></div></div>
<div class="lh-row"><label>아이템 우선</label><div class="lh-tog" id="st-pickup-pri"></div></div>
<div class="lh-row"><label>아데나만</label><div class="lh-tog" id="st-adena"></div></div>
<div class="lh-row"><label>획득 무게 제한</label><div class="lh-tog on" id="st-pw-on"></div></div>
<div class="lh-row"><label>무게 ≤</label><input id="st-pickup-w" type="number" min="10" max="99" value="70"><span class="lh-note">%</span></div>
<div class="lh-sec">⚡ 버프 / 기능 아이템</div>
<div id="lh-buff-box"></div>
<div class="lh-row"><label>기능 아이템</label><button type="button" id="lh-add-func" class="lh-tab">+ 추가</button></div>
<div id="lh-func-box"></div>
<div class="lh-sec">👤 변신</div>
<div class="lh-row"><label>변신 유지</label><div class="lh-tog on" id="st-shape"></div></div>
<div class="lh-row"><label>주문서</label></div>
<div class="lh-keys" id="lh-key-shape"></div>
<div class="lh-row"><label>주 선호</label><span id="lh-pref" class="lh-note">-</span></div>
<div class="lh-note" id="lh-tstatus">○ 변신 확인 중</div>
<div class="lh-tabs">
  <button class="lh-tab on" data-tab="recent" type="button">최근</button>
  <button class="lh-tab" data-tab="fav" type="button">★ 즐겨찾기</button>
  <button class="lh-tab" data-tab="all" type="button">전체</button>
</div>
<input id="st-tsearch" placeholder="변신 검색" autocomplete="off">
<div class="lh-tlist" id="lh-tlist"></div>
<div class="lh-row"><label>만료 전 재사용</label><div class="lh-tog on" id="st-treuse"></div></div>
<div class="lh-row"><label>남은 시간</label><input id="st-treuse-sec" type="number" min="5" max="120" value="20"><span class="lh-note">초</span></div>
<div class="lh-row"><label>실패 재시도</label><input id="st-tretry" type="number" min="0" max="3" value="1"><span class="lh-note">회</span></div>
<div class="lh-row"><label>주문서 없음</label><select id="st-tnoscroll"><option value="continue">변신 없이 계속 사냥</option><option value="stop">BOT 중지</option></select></div>
<div class="lh-row"><label>자동 해독</label><div class="lh-tog on" id="st-anti"></div></div>
<div class="lh-keys" id="lh-key-anti"></div>
<div class="lh-sec">✨ 공격 마법</div>
<div id="lh-skill-box"></div>
<div class="lh-sec">⚔ 사냥</div>
<div class="lh-row"><label>자동 공격</label><div class="lh-tog on" id="st-attack"></div></div>
<div class="lh-row"><label>선공 몬스터 우선</label><div class="lh-tog on" id="st-aggro"></div></div>
<div class="lh-row"><label>매너 사냥</label><div class="lh-tog on" id="st-manner"></div></div>
<div class="lh-row"><label>탐색 범위</label><input id="st-range" type="number" min="1" max="18" value="8"><span class="lh-note">걸음</span></div>
<div class="lh-row"><label>사냥 위치 제한</label><div class="lh-tog on" id="st-anchor-on"></div></div>
<div class="lh-row"><label>위치 제한</label><input id="st-anchor" type="number" min="1" max="18" value="8"><span class="lh-note">걸음</span></div>
<div class="lh-row"><label>타겟 없음</label><input id="st-notarget" type="number" min="3" max="60" value="10"><span class="lh-note">초</span></div>
<div class="lh-row"><label>한 타겟 최대 전투</label><input id="st-timeout" type="number" min="10" max="180" value="60"><span class="lh-note">초</span></div>
<div class="lh-sec">BOT 활성</div>
<div class="lh-row"><label>BOT 활성</label><div class="lh-tog on" id="st-on"></div></div>
<button id="lh-save">저장</button>
<div id="lh-msg"></div>`;

    const $ = id => panel.querySelector('#' + id) || document.getElementById(id);
    function healNote(kind) {
      const p = POTIONS[kind];
      if (!p) return '';
      return '회복 ' + p.healMin + '~' + p.healMax + ' HP · 평균 약 ' + p.healAverage;
    }
    function fillKinds(id, allowEmpty) {
      const el = $(id); if (!el) return;
      el.innerHTML = (allowEmpty ? '<option value="">-</option>' : '') +
        KIND_ORDER.map(k => '<option value="'+k+'">'+POTIONS[k].name+'</option>').join('');
    }
    function paintGrid(elId, prop, allowEmpty) {
      const el = $(elId); if (!el) return;
      const cur = sel[prop];
      const none = allowEmpty ? '<div class="lh-key'+(cur===''?' sel':'')+'" data-k="">-</div>' : '';
      el.innerHTML = none + KEYS.map(k =>
        '<div class="lh-key'+(cur===k?' sel':'')+'" data-k="'+k+'">'+k+'</div>').join('');
      el.querySelectorAll('.lh-key').forEach(b => {
        b.onclick = () => {
          sel[prop] = b.dataset.k;
          el.querySelectorAll('.lh-key').forEach(x => x.classList.toggle('sel', x === b));
        };
      });
    }
    function tog(id, on) {
      const el = $(id); if (!el) return;
      el.classList.toggle('on', !!on);
      el.onclick = () => el.classList.toggle('on');
    }
    function isOn(id) { const el = $(id); return !!(el && el.classList.contains('on')); }
    function paintAll() {
      paintGrid('lh-key-main','main',false);
      paintGrid('lh-key-emg','emg',false);
      paintGrid('lh-key-fb','fb',true);
      paintGrid('lh-key-return','ret',false);
      paintGrid('lh-key-shape','shape',true);
      paintGrid('lh-key-anti','anti',true);
      paintGrid('lh-key-mp1','mp1',true);
      paintGrid('lh-key-mp2','mp2',true);
    }
    function fillSelect(id, items, value) {
      const el = $(id); if (!el) return;
      el.innerHTML = items.map(it => '<option value="'+it.id+'">'+(it.name||it.id)+'</option>').join('');
      if (value) el.value = value;
    }
    function tById(id) { return TRANSFORMS.find(t => t.id === id); }
    function eligibleT(t) {
      const lv = +($('st-level') && $('st-level').value || 27);
      const w = ($('st-weapon') && $('st-weapon').value) || 'sword1h';
      if ((t.minLevel || 1) > lv) return false;
      const wts = t.weaponTypes || ['any'];
      if (wts.indexOf('any') < 0 && wts.indexOf(w) < 0) return false;
      const cls = t.classes || ['any'];
      if (cls.indexOf('any') < 0 && cls.indexOf(charClass) < 0) return false;
      return true;
    }
    function histAt(id) {
      const h = tHist.find(x => x.id === id);
      return h ? (h.lastUsedAt || 0) : 0;
    }
    function ago(ts) {
      if (!ts) return '';
      const d = Date.now() - ts;
      if (d < 120000) return '방금';
      if (d < 3600000) return Math.round(d/60000) + '분 전';
      if (d < 86400000) return Math.round(d/3600000) + '시간 전';
      return Math.round(d/86400000) + '일 전';
    }
    function listedTransforms() {
      let list = TRANSFORMS.filter(eligibleT);
      const q = (($('st-tsearch') && $('st-tsearch').value) || '').trim();
      if (q) {
        const qq = q.toLowerCase();
        list = list.filter(t => (t.name||'').toLowerCase().indexOf(qq) >= 0
          || (t.id||'').toLowerCase().indexOf(qq) >= 0
          || (t.weaponTypes||[]).join(' ').indexOf(qq) >= 0);
      }
      if (tTab === 'fav') list = list.filter(t => tFav.indexOf(t.id) >= 0);
      list = list.slice().sort((a,b) => histAt(b.id) - histAt(a.id));
      if (tTab === 'recent') {
        const rec = list.filter(t => histAt(t.id) > 0).slice(0, 10);
        if (rec.length) list = rec;
      }
      return list;
    }
    function markUsed(id) {
      if (!id) return;
      const now = Date.now();
      const hit = tHist.find(x => x.id === id);
      if (hit) { hit.lastUsedAt = now; hit.useCount = (hit.useCount||0)+1; }
      else tHist.push({id, lastUsedAt: now, useCount: 1});
      tHist.sort((a,b) => (b.lastUsedAt||0)-(a.lastUsedAt||0));
      tHist = tHist.slice(0, 30);
      preferredId = preferredId || id;
    }
    function renderTransforms() {
      const box = $('lh-tlist'); if (!box) return;
      const list = listedTransforms();
      box.innerHTML = list.map(t => {
        const star = tFav.indexOf(t.id) >= 0;
        const selc = t.id === preferredId ? ' sel' : '';
        return '<div class="lh-titem'+selc+'" data-id="'+t.id+'">'
          + '<button type="button" class="lh-star'+(star?' on':'')+'" data-star="'+t.id+'">'+(star?'★':'☆')+'</button>'
          + '<span style="flex:1">'+t.name+'</span>'
          + '<span class="lh-note">'+ago(histAt(t.id))+'</span></div>';
      }).join('') || '<div class="lh-note" style="padding:8px">조건에 맞는 변신 없음</div>';
      box.querySelectorAll('.lh-titem').forEach(row => {
        row.onclick = (e) => {
          if (e.target && e.target.dataset.star) return;
          preferredId = row.dataset.id;
          markUsed(preferredId);
          renderTransforms();
          syncPref();
        };
      });
      box.querySelectorAll('[data-star]').forEach(b => {
        b.onclick = (e) => {
          e.stopPropagation();
          const id = b.dataset.star;
          const i = tFav.indexOf(id);
          if (i >= 0) tFav.splice(i,1); else tFav.push(id);
          renderTransforms();
        };
      });
      document.querySelectorAll('.lh-tab').forEach(tb => tb.classList.toggle('on', tb.dataset.tab === tTab));
      syncPref();
    }
    function syncPref() {
      const t = tById(preferredId);
      if ($('lh-pref')) $('lh-pref').textContent = t ? ('★ ' + t.name) : '-';
    }
    function renderBuffs() {
      const box = $('lh-buff-box'); if (!box) return;
      const cfg = CLASS_CONFIG[charClass] || CLASS_CONFIG.knight || {buffs:[]};
      box.innerHTML = (cfg.buffs || []).map(b => {
        const on = buffOn[b.id] !== false;
        const key = buffKey[b.id] || '';
        let extra = '';
        if (b.variants) {
          extra = '<div class="lh-row"><label>종류</label><select data-bvar="'+b.id+'">'
            + b.variants.map(v => '<option value="'+v.name+'">'+v.name+'</option>').join('')
            + '</select></div>';
        }
        return '<div class="lh-b" data-bid="'+b.id+'">'
          + '<div class="lh-row"><label>'+(b.name||b.label)+'</label>'
          + '<div class="lh-tog'+(on?' on':'')+'" data-btog="'+b.id+'"></div></div>'
          + '<div class="lh-note">'+(fmtRemain(b.id) || b.note || (b.durationMin ? ('지속 약 '+b.durationMin+'분') : ''))+'</div>'
          + extra
          + '<div class="lh-keys" data-bkeys="'+b.id+'"></div></div>';
      }).join('');
      box.querySelectorAll('[data-btog]').forEach(el => {
        el.onclick = () => {
          el.classList.toggle('on');
          buffOn[el.dataset.btog] = el.classList.contains('on');
        };
      });
      box.querySelectorAll('[data-bkeys]').forEach(el => {
        const id = el.dataset.bkeys;
        const cur = buffKey[id] || '';
        el.innerHTML = '<div class="lh-key'+(cur===''?' sel':'')+'" data-k="">-</div>'
          + KEYS.map(k => '<div class="lh-key'+(cur===k?' sel':'')+'" data-k="'+k+'">'+k+'</div>').join('');
        el.querySelectorAll('.lh-key').forEach(b => {
          b.onclick = () => {
            buffKey[id] = b.dataset.k;
            el.querySelectorAll('.lh-key').forEach(x => x.classList.toggle('sel', x === b));
          };
        });
      });
      panel.classList.toggle('wizard', charClass === 'wizard');
    }
    function fmtRemain(id) {
      const sec = buffRemain[id];
      if (sec == null || !Number.isFinite(sec) || sec < 0) return '';
      const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
      return String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
    }
    function classSkills() { return SKILLS[charClass] || SKILLS.knight || [{id:'none', name:'-'}]; }
    function renderFuncItems() {
      const box = $('lh-func-box'); if (!box) return;
      const cat = FUNC_CATALOG.length ? FUNC_CATALOG : [{id:'green', name:'초록 물약', triggerType:'TIMER', duration:300}];
      box.innerHTML = funcItems.map((it, i) => {
        const opts = cat.map(c => '<option value="'+c.id+'"'+(c.id===it.itemId?' selected':'')+'>'+c.name+'</option>').join('');
        return '<div class="lh-b" data-fi="'+i+'">'
          + '<div class="lh-row"><select data-fi-id="'+i+'">'+opts+'</select>'
          + '<div class="lh-tog'+(it.enabled!==false?' on':'')+'" data-fi-on="'+i+'"></div>'
          + '<button type="button" class="lh-tab" data-fi-del="'+i+'">삭제</button></div>'
          + '<div class="lh-row"><label>키</label><select data-fi-key="'+i+'"><option value="">-</option>'
          + KEYS.map(k=>'<option value="'+k+'"'+(it.hotkey===k?' selected':'')+'>'+k+'</option>').join('')
          + '</select></div></div>';
      }).join('');
      box.querySelectorAll('[data-fi-on]').forEach(el => { el.onclick = () => { el.classList.toggle('on'); const i=+el.dataset.fiOn; funcItems[i].enabled = el.classList.contains('on'); }; });
      box.querySelectorAll('[data-fi-id]').forEach(el => { el.onchange = () => { const i=+el.dataset.fiId; const c=cat.find(x=>x.id===el.value)||{}; funcItems[i].itemId=c.id; funcItems[i].name=c.name; funcItems[i].triggerType=c.triggerType; funcItems[i].duration=c.duration||0; }; });
      box.querySelectorAll('[data-fi-key]').forEach(el => { el.onchange = () => { funcItems[+el.dataset.fiKey].hotkey = el.value; }; });
      box.querySelectorAll('[data-fi-del]').forEach(el => { el.onclick = () => { funcItems.splice(+el.dataset.fiDel,1); renderFuncItems(); }; });
    }
    function renderSkills() {
      const box = $('lh-skill-box'); if (!box) return;
      const pool = classSkills();
      while (attackSkills.length < 8) attackSkills.push({id:'none', name:'-', enabled:false, key:'', mpMin:0, hpMin:0, targetHpMax:100, intervalSec:3, maxCount:0});
      attackSkills = attackSkills.slice(0,8);
      box.innerHTML = attackSkills.map((sk, i) => {
        const opts = pool.map(p => '<option value="'+p.id+'"'+(p.id===sk.id?' selected':'')+'>'+p.name+'</option>').join('');
        return '<div class="lh-b">'
          + '<div class="lh-row"><label>'+(i+1)+'</label><select data-sk="'+i+'">'+opts+'</select>'
          + '<button type="button" class="lh-tab" data-up="'+i+'">↑</button>'
          + '<button type="button" class="lh-tab" data-dn="'+i+'">↓</button></div>'
          + '<div class="lh-row"><label>자동</label><div class="lh-tog'+(sk.enabled?' on':'')+'" data-sk-on="'+i+'"></div>'
          + '<label>간격</label><input type="number" min="0" max="30" value="'+(sk.intervalSec||3)+'" data-sk-iv="'+i+'"></div>'
          + '<div class="lh-row"><label>MP≥</label><input type="number" min="0" max="100" value="'+(sk.mpMin||0)+'" data-sk-mp="'+i+'">'
          + '<label>HP≥</label><input type="number" min="0" max="100" value="'+(sk.hpMin||0)+'" data-sk-hp="'+i+'"></div></div>';
      }).join('');
      const sync = (i, field, val) => { attackSkills[i][field] = val; };
      box.querySelectorAll('[data-sk]').forEach(el => { el.onchange = () => { const i=+el.dataset.sk; const p=pool.find(x=>x.id===el.value)||{id:'none',name:'-'}; attackSkills[i].id=p.id; attackSkills[i].name=p.name; }; });
      box.querySelectorAll('[data-sk-on]').forEach(el => { el.onclick = () => { el.classList.toggle('on'); attackSkills[+el.dataset.skOn].enabled = el.classList.contains('on'); }; });
      box.querySelectorAll('[data-sk-iv]').forEach(el => { el.onchange = () => sync(+el.dataset.skIv,'intervalSec', +el.value); });
      box.querySelectorAll('[data-sk-mp]').forEach(el => { el.onchange = () => sync(+el.dataset.skMp,'mpMin', +el.value); });
      box.querySelectorAll('[data-sk-hp]').forEach(el => { el.onchange = () => sync(+el.dataset.skHp,'hpMin', +el.value); });
      box.querySelectorAll('[data-up]').forEach(el => { el.onclick = () => { const i=+el.dataset.up; if(i<=0)return; const t=attackSkills[i-1]; attackSkills[i-1]=attackSkills[i]; attackSkills[i]=t; renderSkills(); }; });
      box.querySelectorAll('[data-dn]').forEach(el => { el.onclick = () => { const i=+el.dataset.dn; if(i>=7)return; const t=attackSkills[i+1]; attackSkills[i+1]=attackSkills[i]; attackSkills[i]=t; renderSkills(); }; });
    }
    function snapshotNow() {
      return {
        main_potion: { key: sel.main, kind: ($('st-kind-main')||{}).value || '주홍' },
        emergency_potion: { key: sel.emg, kind: ($('st-kind-emg')||{}).value || '맑은' },
        backup_potion: { key: sel.emg, kind: ($('st-kind-emg')||{}).value || '맑은' },
        fallback_potion: { key: sel.fb, kind: ($('st-kind-fb')||{}).value || '' },
        potion_key: sel.main, potion_key_alt: sel.emg, return_key: sel.ret,
        potion_start_pct: +(($('st-hp-main')||{}).value || 80),
        emergency_pct: +(($('st-hp-emg')||{}).value || 45),
        danger_pct: +(($('st-danger')||{}).value || 20),
        buff_green: buffOn.haste1 !== false,
        buff_green_kind: (panel.querySelector('[data-bvar="haste1"]')||{}).value || '초록 물약',
        buff_green_key: buffKey.haste1 || '',
        buff_haste2: buffOn.haste2 !== false,
        buff_haste2_kind: ((CLASS_CONFIG[charClass]||{}).buffs||[]).filter(b=>b.id==='haste2')[0] ? ((CLASS_CONFIG[charClass]||{}).buffs||[]).filter(b=>b.id==='haste2')[0].name : '',
        buff_haste2_key: buffKey.haste2 || '',
        buff_wisdom: buffOn.wisdom !== false,
        buff_wisdom_key: buffKey.wisdom || '',
        buff_blue: buffOn.blue !== false,
        buff_blue_key: buffKey.blue || '',
        shapechange: isOn('st-shape'),
        shapechange_key: sel.shape,
        preferredTransformId: preferredId,
        fallbackTransformId: fallbackId,
        transformFavorites: tFav.slice(),
        transformHistory: tHist.slice(),
        transformKey: sel.shape,
        weaponType: ($('st-weapon')||{}).value || 'sword1h',
      };
    }
    function applySnap(p) {
      if (!p) return;
      if (p.main_potion) { sel.main = p.main_potion.key || sel.main; if (p.main_potion.kind && $('st-kind-main')) $('st-kind-main').value = p.main_potion.kind; }
      if (p.emergency_potion) { sel.emg = p.emergency_potion.key || sel.emg; if (p.emergency_potion.kind && $('st-kind-emg')) $('st-kind-emg').value = p.emergency_potion.kind; }
      if (p.fallback_potion) sel.fb = p.fallback_potion.key || sel.fb;
      if (p.return_key) sel.ret = p.return_key;
      if (p.potion_start_pct != null && $('st-hp-main')) $('st-hp-main').value = p.potion_start_pct;
      if (p.emergency_pct != null && $('st-hp-emg')) $('st-hp-emg').value = p.emergency_pct;
      if (p.danger_pct != null && $('st-danger')) $('st-danger').value = p.danger_pct;
      buffOn.haste1 = p.buff_green !== false;
      buffOn.haste2 = p.buff_haste2 !== false;
      buffOn.wisdom = p.buff_wisdom !== false;
      buffOn.blue = p.buff_blue !== false;
      buffKey.haste1 = p.buff_green_key || '';
      buffKey.haste2 = p.buff_haste2_key || '';
      buffKey.wisdom = p.buff_wisdom_key || '';
      buffKey.blue = p.buff_blue_key || '';
      if (p.shapechange_key) sel.shape = p.shapechange_key;
      if (p.preferredTransformId) preferredId = p.preferredTransformId;
      if (p.fallbackTransformId) fallbackId = p.fallbackTransformId;
      if (Array.isArray(p.transformFavorites)) tFav = p.transformFavorites.slice();
      if (Array.isArray(p.transformHistory)) tHist = p.transformHistory.slice();
      if (p.weaponType && $('st-weapon')) $('st-weapon').value = p.weaponType;
      if ($('st-shape')) $('st-shape').classList.toggle('on', p.shapechange !== false);
    }
    function changeClass(next) {
      classProfiles[charClass] = snapshotNow();
      charClass = next;
      if (classProfiles[charClass]) applySnap(classProfiles[charClass]);
      else {
        const cfg = CLASS_CONFIG[charClass] || {};
        const h2 = (cfg.buffs||[]).find(b => b.id === 'haste2');
        if (h2) { buffOn.haste2 = true; }
      }
      renderBuffs();
      renderTransforms();
      renderFuncItems();
      renderSkills();
      paintAll();
      syncNotes();
      if ($('lh-save') && $('lh-save').onclick) $('lh-save').onclick();
    }
    function findLaunchButton() {
      return [...document.querySelectorAll('button')].find(b =>
        (b.textContent || '').replace(/\s+/g,' ').trim() === '+ 게임 실행');
    }
    function sizeSlot(slot) {
      if (!slot) return;
      const top = slot.getBoundingClientRect().top;
      const aside = document.querySelector('aside');
      const bottom = aside ? aside.getBoundingClientRect().bottom : innerHeight;
      slot.style.maxHeight = Math.max(180, Math.round(bottom - top - 8)) + 'px';
    }
    function mountHud() {
      const old = document.getElementById('linc-hud-slot');
      const btn = findLaunchButton();
      if (old && btn && btn.parentElement && old.previousElementSibling === btn.parentElement && old.contains(panel)) {
        sizeSlot(old);
        return true;
      }
      if (old) old.remove();
      const slot = document.createElement('div');
      slot.id = 'linc-hud-slot';
      slot.appendChild(panel);
      if (btn && btn.parentElement && btn.parentElement.parentElement) {
        btn.parentElement.after(slot);
        sizeSlot(slot);
        return true;
      }
      const aside = document.querySelector('aside');
      if (aside) { aside.appendChild(slot); sizeSlot(slot); return true; }
      document.body.appendChild(slot);
      sizeSlot(slot);
      return false;
    }

    mountHud();
    fillKinds('st-kind-main', false);
    fillKinds('st-kind-emg', false);
    fillKinds('st-kind-fb', true);
    $('st-kind-main').value = '주홍';
    $('st-kind-emg').value = '맑은';
    $('st-kind-fb').value = '빨간';
    const syncNotes = () => {
      $('note-main').textContent = healNote($('st-kind-main').value);
      $('note-emg').textContent = healNote($('st-kind-emg').value);
    };
    $('st-kind-main').onchange = syncNotes;
    $('st-kind-emg').onchange = syncNotes;
    syncNotes();
    paintAll();
    fillSelect('st-class', CLASSES, 'knight');
    fillSelect('st-weapon', WEAPONS, 'sword1h');
    ['st-fallback','st-return','st-empty-return','st-weight-return','st-pickup','st-shape','st-anti','st-attack','st-aggro','st-manner','st-on','st-treuse'].forEach(id => tog(id, true));
    tog('st-idle-return', false);
    tog('st-pickup-pri', false);
    tog('st-adena', false);
    tog('st-mp-on', false);
    tog('st-mp-return', false);
    tog('st-pw-on', true);
    tog('st-anchor-on', true);
    fillSelect('st-mp1', MP_POTIONS, '');
    fillSelect('st-mp2', MP_POTIONS, '');
    renderBuffs();
    renderTransforms();
    renderFuncItems();
    renderSkills();
    if ($('lh-add-func')) $('lh-add-func').onclick = () => {
      const c = (FUNC_CATALOG[0] || {id:'green', name:'초록 물약', triggerType:'TIMER', duration:300});
      funcItems.push({itemId:c.id, name:c.name, hotkey:'', enabled:true, triggerType:c.triggerType||'TIMER', duration:c.duration||0, refreshBefore:10});
      renderFuncItems();
    };
    if ($('st-class')) $('st-class').onchange = () => changeClass($('st-class').value);
    if ($('st-weapon')) $('st-weapon').onchange = () => renderTransforms();
    if ($('st-level')) $('st-level').onchange = () => renderTransforms();
    if ($('st-tsearch')) $('st-tsearch').oninput = () => renderTransforms();
    document.querySelectorAll('.lh-tab').forEach(tb => {
      tb.onclick = () => { tTab = tb.dataset.tab; renderTransforms(); };
    });

    function applyCatalog(s) {
      if (s && s.potions) {
        Object.keys(s.potions).forEach(k => { POTIONS[k] = s.potions[k]; });
      }
      if (s && s.classConfig) CLASS_CONFIG = s.classConfig;
      if (s && s.classes) CLASSES = s.classes;
      if (s && s.weapons) WEAPONS = s.weapons;
      if (s && s.transforms) TRANSFORMS = s.transforms;
      if (s && s.skills) SKILLS = s.skills;
      if (s && s.funcItemCatalog) FUNC_CATALOG = s.funcItemCatalog;
      if (s && s.mpPotions) MP_POTIONS = s.mpPotions;
    }
    async function loadSet() {
      try {
        const s = await (await fetch(S + '/bot-settings')).json();
        applyCatalog(s);
        const mp = s.main_potion || {};
        const ep = s.emergency_potion || s.backup_potion || {};
        const fp = s.fallback_potion || {};
        sel.main = mp.key || s.potion_key || sel.main;
        sel.emg = ep.key || sel.emg;
        sel.fb = fp.key || sel.fb;
        sel.ret = s.return_key || sel.ret;
        sel.shape = s.shapechange_key || s.transformKey || 'F3';
        sel.anti = s.antidote_key || 'F2';
        charClass = s.characterClass || 'knight';
        classProfiles = s.classProfiles || {};
        tFav = Array.isArray(s.transformFavorites) ? s.transformFavorites.slice() : [];
        tHist = Array.isArray(s.transformHistory) ? s.transformHistory.slice() : [];
        preferredId = s.preferredTransformId || preferredId;
        fallbackId = s.fallbackTransformId || fallbackId;
        buffOn.haste1 = s.buff_green !== false;
        buffOn.haste2 = s.buff_haste2 !== false;
        buffOn.wisdom = s.buff_wisdom !== false;
        buffOn.blue = s.buff_blue !== false;
        buffKey.haste1 = s.buff_green_key || '';
        buffKey.haste2 = s.buff_haste2_key || '';
        buffKey.wisdom = s.buff_wisdom_key || '';
        buffKey.blue = s.buff_blue_key || '';
        fillSelect('st-class', CLASSES, charClass);
        fillSelect('st-weapon', WEAPONS, s.weaponType || 'sword1h');
        if ($('st-level') && s.characterLevel != null) $('st-level').value = s.characterLevel;
        if ($('st-treuse-sec') && s.transformReuseBeforeSec != null) $('st-treuse-sec').value = s.transformReuseBeforeSec;
        if ($('st-tretry') && s.transformRetryMax != null) $('st-tretry').value = s.transformRetryMax;
        if ($('st-tnoscroll') && s.transformNoScrollAction) $('st-tnoscroll').value = s.transformNoScrollAction;
        if (POTIONS[mp.kind]) $('st-kind-main').value = mp.kind;
        if (POTIONS[ep.kind]) $('st-kind-emg').value = ep.kind;
        if (POTIONS[fp.kind] || fp.kind === '') $('st-kind-fb').value = fp.kind || '';
        $('st-hp-main').value = s.potion_start_pct != null ? s.potion_start_pct : 80;
        $('st-hp-emg').value = s.emergency_pct != null ? s.emergency_pct : 45;
        $('st-danger').value = s.danger_pct != null ? s.danger_pct : 20;
        $('st-weight-pct').value = s.weight_return_pct != null ? s.weight_return_pct : 80;
        if ($('st-idle-sec')) $('st-idle-sec').value = s.no_combat_sec != null ? s.no_combat_sec : (s.no_combat_minutes != null ? s.no_combat_minutes * 60 : 600);
        if ($('st-mp1-pct') && s.mp_start_pct != null) $('st-mp1-pct').value = s.mp_start_pct;
        if ($('st-mp2-pct') && s.mp_emergency_pct != null) $('st-mp2-pct').value = s.mp_emergency_pct;
        if ($('st-mp-ret') && s.mp_return_pct != null) $('st-mp-ret').value = s.mp_return_pct;
        if ($('st-anchor') && s.hunt_anchor_range != null) $('st-anchor').value = s.hunt_anchor_range;
        fillSelect('st-mp1', MP_POTIONS, (s.mp_potion||{}).kind || '');
        fillSelect('st-mp2', MP_POTIONS, (s.mp_potion2||{}).kind || '');
        sel.mp1 = (s.mp_potion||{}).key || '';
        sel.mp2 = (s.mp_potion2||{}).key || '';
        funcItems = Array.isArray(s.func_items) ? s.func_items.slice() : [];
        attackSkills = Array.isArray(s.attack_skills) ? s.attack_skills.slice() : [];
        buffRemain = s.buff_remain || {};
        if ($('st-mp-on') && s.mp_recover_enabled != null) $('st-mp-on').classList.toggle('on', !!s.mp_recover_enabled);
        if ($('st-mp-return') && s.mp_return_enabled != null) $('st-mp-return').classList.toggle('on', !!s.mp_return_enabled);
        if ($('st-pw-on') && s.pickup_weight_enabled != null) $('st-pw-on').classList.toggle('on', !!s.pickup_weight_enabled);
        $('st-pickup-w').value = s.pickup_weight_pct != null ? s.pickup_weight_pct : 70;
        $('st-range').value = s.search_range != null ? s.search_range : 10;
        $('st-notarget').value = s.no_target_sec != null ? s.no_target_sec : 10;
        $('st-timeout').value = s.target_timeout_sec != null ? s.target_timeout_sec : 60;
        const flags = {
          'st-fallback': s.fallback_on_empty, 'st-return': s.return_enabled,
          'st-empty-return': s.potion_empty_return, 'st-weight-return': s.weight_return,
          'st-idle-return': s.no_combat_return, 'st-pickup': s.pickup_enabled,
          'st-pickup-pri': s.pickup_priority, 'st-adena': s.adena_only,
          'st-shape': s.shapechange, 'st-anti': s.antidote,
          'st-attack': s.auto_attack, 'st-aggro': s.aggro_first,
          'st-manner': s.manner_hunt, 'st-on': s.enabled
        };
        Object.keys(flags).forEach(id => { if (flags[id] != null && $(id)) $(id).classList.toggle('on', !!flags[id]); });
        syncNotes();
        paintAll();
        renderBuffs();
        renderTransforms();
        renderFuncItems();
        renderSkills();
      } catch (e) { console.log('[linc-hud] settings load fail', e && e.message); }
    }
    $('lh-save').onclick = async () => {
      const kMain = $('st-kind-main').value || '주홍';
      const kEmg = $('st-kind-emg').value || '맑은';
      const kFb = $('st-kind-fb').value || '';
      const body = {
        main_potion: { key: sel.main, kind: kMain },
        emergency_potion: { key: sel.emg, kind: kEmg },
        backup_potion: { key: sel.emg, kind: kEmg },
        fallback_potion: { key: sel.fb, kind: kFb },
        potion_key: sel.main, orange_key: sel.main, potion_key_alt: sel.emg,
        return_key: sel.ret,
        potion_start_pct: +$('st-hp-main').value,
        emergency_pct: +$('st-hp-emg').value, red_pct: +$('st-hp-emg').value,
        danger_pct: +$('st-danger').value,
        fallback_on_empty: isOn('st-fallback'),
        return_enabled: isOn('st-return'),
        potion_empty_return: isOn('st-empty-return'),
        weight_return: isOn('st-weight-return'),
        weight_return_pct: +$('st-weight-pct').value,
        no_combat_return: isOn('st-idle-return'),
        no_combat_sec: +(($('st-idle-sec')||{}).value || 600),
        no_combat_minutes: Math.round((+(($('st-idle-sec')||{}).value || 600)) / 60),
        mp_recover_enabled: isOn('st-mp-on'),
        mp_potion: { key: sel.mp1, kind: ($('st-mp1')||{}).value || '' },
        mp_potion2: { key: sel.mp2, kind: ($('st-mp2')||{}).value || '' },
        mp_start_pct: +(($('st-mp1-pct')||{}).value || 30),
        mp_emergency_pct: +(($('st-mp2-pct')||{}).value || 15),
        mp_return_enabled: isOn('st-mp-return'),
        mp_return_pct: +(($('st-mp-ret')||{}).value || 10),
        pickup_weight_enabled: isOn('st-pw-on'),
        hunt_anchor_range: +(($('st-anchor')||{}).value || 8),
        func_items: funcItems,
        attack_skills: attackSkills,
        pickup_enabled: isOn('st-pickup'),
        pickup_priority: isOn('st-pickup-pri'),
        adena_only: isOn('st-adena'),
        pickup_weight_pct: +$('st-pickup-w').value,
        characterClass: charClass,
        characterLevel: +(($('st-level')||{}).value || 27),
        weaponType: ($('st-weapon')||{}).value || 'sword1h',
        classProfiles: Object.assign({}, classProfiles, {[charClass]: snapshotNow()}),
        buff_green: buffOn.haste1 !== false,
        buff_green_kind: (panel.querySelector('[data-bvar="haste1"]')||{}).value || '초록 물약',
        buff_green_key: buffKey.haste1 || '',
        buff_haste2: buffOn.haste2 !== false,
        buff_haste2_kind: (((CLASS_CONFIG[charClass]||{}).buffs||[]).find(b=>b.id==='haste2')||{}).name || '',
        buff_haste2_key: buffKey.haste2 || '',
        buff_wisdom: buffOn.wisdom !== false,
        buff_wisdom_key: buffKey.wisdom || '',
        buff_blue: buffOn.blue !== false,
        buff_blue_key: buffKey.blue || '',
        shapechange: isOn('st-shape'),
        shapechange_key: sel.shape,
        preferredTransformId: preferredId,
        fallbackTransformId: fallbackId,
        transformFavorites: tFav,
        transformHistory: tHist,
        transformKey: sel.shape,
        transformReuseBeforeSec: +(($('st-treuse-sec')||{}).value || 20),
        transformRetryMax: +(($('st-tretry')||{}).value || 1),
        transformNoScrollAction: ($('st-tnoscroll')||{}).value || 'continue',
        antidote: isOn('st-anti'),
        antidote_key: sel.anti,
        auto_attack: isOn('st-attack'),
        aggro_first: isOn('st-aggro'),
        manner_hunt: isOn('st-manner'),
        search_range: +$('st-range').value,
        no_target_sec: +$('st-notarget').value,
        target_timeout_sec: +$('st-timeout').value,
        enabled: isOn('st-on')
      };
      try {
        await fetch(S + '/bot-settings', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
        $('lh-msg').textContent = '저장됨';
        setTimeout(() => { $('lh-msg').textContent = ''; }, 2000);
      } catch (e) { $('lh-msg').textContent = '저장 실패'; }
    };
    let pollBusy = false;
    async function poll() {
      if (pollBusy) return;
      pollBusy = true;
      try {
        const r = await (await fetch(S + '/hp')).json();
        let hp = null;
        if (typeof r.ratio === 'number') hp = r.ratio;
        else if (r.bot && r.bot.ratio != null) hp = r.bot.ratio;
        else if (r.hp != null && r.hp_max) hp = r.hp / r.hp_max;
        if (hp != null && Number.isFinite(hp)) {
          hp = Math.max(0, Math.min(1, hp));
          $('lh-fill').style.width = Math.round(hp * 100) + '%';
          $('lh-fill').style.background = hp < 0.45 ? 'linear-gradient(90deg,#e5484d,#ff8a8a)'
            : hp < 0.8 ? 'linear-gradient(90deg,#f5b431,#ffd76e)' : 'linear-gradient(90deg,#37d67a,#8ff5b3)';
          $('lh-hp').textContent = 'HP ' + Math.round(hp * 100) + '%';
        } else {
          $('lh-hp').textContent = 'HP --%';
        }
        let mp = null;
        if (r.bot && r.bot.mp != null) mp = r.bot.mp;
        else if (typeof r.mp === 'number') mp = r.mp;
        if ($('lh-mp')) $('lh-mp').textContent = (mp != null && Number.isFinite(mp)) ? ('MP ' + Math.round(mp * 100) + '%') : 'MP --%';
        const bits = [];
        if (r.bot) bits.push('사냥 중');
        else bits.push('봇 대기 중');
        if (mp != null && Number.isFinite(mp) && charClass !== 'wizard') bits.push('MP ' + Math.round(mp * 100) + '%');
        if (r.bot && r.bot.weight != null) bits.push('무게 ' + Math.round(r.bot.weight * 100) + '%');
        else if (typeof r.weight === 'number') bits.push('무게 ' + Math.round(r.weight * 100) + '%');
        $('lh-sub').textContent = bits.join(' · ');
        const warn = [];
        if (hp == null && !r.bot) warn.push('');
        if (r.bot && r.bot.warn) warn.push('⚠ ' + r.bot.warn);
        if (r.bot && r.bot.buffs) buffRemain = r.bot.buffs;
        $('lh-warn').textContent = warn.filter(Boolean).join(' · ');
      } catch (e) {
        $('lh-sub').textContent = '수신 없음';
        $('lh-warn').textContent = '⚠ 게임창 없음';
      } finally {
        pollBusy = false;
      }
    }

    window.__lincHudMountTimer = setInterval(mountHud, 2500);
    window.__lincHudUiTimer = setInterval(poll, 50);
    poll();
    loadSet();
    return 'linc-hud-v1';
  }
  installHudUi();
})();
