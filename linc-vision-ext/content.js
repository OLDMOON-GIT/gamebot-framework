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
})();
