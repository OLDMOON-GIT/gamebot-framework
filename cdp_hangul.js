#!/usr/bin/env node
// CDP Input.dispatchKeyEvent 로 한영키(Lang1 / VK_HANGUL=21)를 퍼플온 페이지에 주입
// 사용: node cdp_hangul.js [뒤에_칠_문자열]
const WebSocket = require('/home/oldmoon/workspace/node_modules/ws');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function connect() {
  const targets = await fetch('http://127.0.0.1:9333/json').then((r) => r.json());
  const page = targets.find((t) => t.type === 'page' && t.url.includes('purpleon'));
  if (!page) throw new Error('purpleon 페이지 없음');
  const ws = new WebSocket(page.webSocketDebuggerUrl, { perMessageDeflate: false });
  let id = 0;
  const pending = new Map();
  ws.on('message', (b) => {
    const m = JSON.parse(b.toString());
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  });
  await new Promise((r) => ws.on('open', r));
  const send = (method, params = {}) =>
    new Promise((res) => { const mid = ++id; pending.set(mid, res); ws.send(JSON.stringify({ id: mid, method, params })); });
  return { ws, send };
}

async function main() {
  const { ws, send } = await connect();
  // 게임 캔버스에 포커스
  await send('Runtime.evaluate', {
    expression: `(() => { const c = document.querySelector('video,canvas'); if (c) { c.focus(); const r = c.getBoundingClientRect(); return r.width + 'x' + r.height; } return 'no-canvas'; })()`,
    returnByValue: true,
  }).then((r) => console.log('캔버스:', r.result?.result?.value));

  // 한영키 주입
  for (const type of ['rawKeyDown', 'keyUp']) {
    await send('Input.dispatchKeyEvent', {
      type,
      key: 'HangulMode',
      code: 'Lang1',
      windowsVirtualKeyCode: 21,
      nativeVirtualKeyCode: 21,
      location: 0,
    });
    await sleep(60);
  }
  console.log('한영키(Lang1/VK21) 주입 완료');

  const text = process.argv[2] || '';
  for (const ch of text) {
    const vk = ch.toUpperCase().charCodeAt(0);
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: ch, code: 'Key' + ch.toUpperCase(), text: ch, unmodifiedText: ch, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk });
    await sleep(40);
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: ch, code: 'Key' + ch.toUpperCase(), windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk });
    await sleep(60);
  }
  if (text) console.log('문자 입력 완료:', text);
  await sleep(300);
  ws.close();
}

main().catch((e) => { console.error('오류:', e.message); process.exit(1); });
