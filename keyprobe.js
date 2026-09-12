#!/usr/bin/env node
// 한영키가 실제로 크롬 페이지까지 도달하는지 CDP로 확인하는 진단 스크립트
// 사용: node keyprobe.js  → 리스너 설치 후 xdotool로 Hangul/g 입력, 수신 이벤트 출력
const WebSocket = require('/home/oldmoon/workspace/node_modules/ws');
const { execSync } = require('child_process');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const targets = await fetch('http://127.0.0.1:9333/json').then((r) => r.json());
  const page = targets.find((t) => t.type === 'page' && t.url.includes('purpleon'));
  if (!page) throw new Error('purpleon 페이지 없음');
  const ws = new WebSocket(page.webSocketDebuggerUrl, { perMessageDeflate: false });
  let id = 0;
  const pending = new Map();
  ws.on('message', (buf) => {
    const msg = JSON.parse(buf.toString());
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    }
  });
  const send = (method, params = {}) =>
    new Promise((res) => {
      const mid = ++id;
      pending.set(mid, res);
      ws.send(JSON.stringify({ id: mid, method, params }));
    });
  await new Promise((r) => ws.on('open', r));

  const install = `
    window.__keys = [];
    if (!window.__keyProbeInstalled) {
      window.__keyProbeInstalled = true;
      for (const ev of ['keydown','keyup','compositionstart','compositionupdate','compositionend','input','textInput']) {
        window.addEventListener(ev, (e) => {
          window.__keys.push({
            t: ev,
            key: e.key,
            code: e.code,
            keyCode: e.keyCode,
            which: e.which,
            isComposing: e.isComposing,
            data: e.data,
            target: (e.target && e.target.tagName) || '',
          });
        }, true);
      }
    }
    'installed:' + document.activeElement.tagName;
  `;
  const r1 = await send('Runtime.evaluate', { expression: install, returnByValue: true });
  console.log('설치:', JSON.stringify(r1.result?.result?.value));

  execSync('DISPLAY=:0 xdotool key --window ' + (process.env.WIN || '') + ' 2>/dev/null || true', { shell: '/bin/bash' });
  // 실제 X11 키 입력
  const keys = process.env.KEYS || 'Hangul g k s d u d';
  execSync(`DISPLAY=:0 xdotool key --delay 200 ${keys}`, { shell: '/bin/bash' });
  await sleep(1200);

  const r2 = await send('Runtime.evaluate', {
    expression: 'JSON.stringify(window.__keys)',
    returnByValue: true,
  });
  const events = JSON.parse(r2.result?.result?.value || '[]');
  console.log('수신 이벤트 수:', events.length);
  for (const e of events) {
    console.log(
      `${e.t.padEnd(18)} key=${String(e.key).padEnd(12)} code=${String(e.code).padEnd(14)} keyCode=${e.keyCode} comp=${e.isComposing} data=${e.data ?? ''} tgt=${e.target}`
    );
  }
  ws.close();
}

main().catch((e) => {
  console.error('오류:', e.message);
  process.exit(1);
});
