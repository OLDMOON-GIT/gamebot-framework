#!/usr/bin/env node
// 퍼플온 페이지에 keydown 프로브를 심고, 일정 시간 수집한 이벤트를 출력
const WebSocket = require('/home/oldmoon/workspace/node_modules/ws');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const targets = await fetch('http://127.0.0.1:9333/json').then((r) => r.json());
  const page = targets.find((t) => t.type === 'page' && t.url.includes('purpleon'));
  if (!page) throw new Error('purpleon 페이지 없음');
  const ws = new WebSocket(page.webSocketDebuggerUrl, { perMessageDeflate: false });
  let id = 0; const pending = new Map();
  ws.on('message', (b) => { const m = JSON.parse(b.toString()); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
  await new Promise((r) => ws.on('open', r));
  const send = (method, params = {}) => new Promise((res) => { const mid = ++id; pending.set(mid, res); ws.send(JSON.stringify({ id: mid, method, params })); });
  const evalJs = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true })).result?.result?.value;

  const mode = process.argv[2] || 'install';
  if (mode === 'install') {
    await evalJs(`(() => { window.__kp = []; if (window.__kpH) window.removeEventListener('keydown', window.__kpH, true);
      window.__kpH = (e) => window.__kp.push({k: e.key, c: e.code, kc: e.keyCode, w: e.which, loc: e.location});
      window.addEventListener('keydown', window.__kpH, true); return 'installed'; })()`).then(console.log);
  } else if (mode === 'dump') {
    console.log(JSON.stringify(await evalJs(`JSON.stringify(window.__kp || [])`)));
  }
  ws.close();
}
main().catch((e) => { console.error('오류:', e.message); process.exit(1); });
