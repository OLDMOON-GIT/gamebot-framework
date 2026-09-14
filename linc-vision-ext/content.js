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
      const blob = await blobOf(hudCanvas, 'image/png');
      if (blob) {
        await post('/hud', blob, {
          'Content-Type': 'image/png',
          'X-Origin-X': String(HUD.x),
          'X-Origin-Y': String(HUD.y),
          'X-Native-W': String(v.videoWidth),
          'X-Native-H': String(v.videoHeight),
          'X-Ts': String(Date.now()),
        });
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
