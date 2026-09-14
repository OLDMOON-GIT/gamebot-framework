// linc-bot 팝업 — ext_bridge.py 의 /ui 채널에 붙어 봇을 켜고 끄고 로그를 본다.
// 팝업 Origin 은 chrome-extension://<id> 라 브리지의 /ui Origin 검사를 통과한다.
const UI_URL = "ws://127.0.0.1:9335/ui";
const $ = (id) => document.getElementById(id);

let ws = null;
let nextId = 0;
const pending = new Map();
let botRunning = false;

function toast(msg, ms = 2500) {
  const t = $("toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => { t.hidden = true; }, ms);
}

function fmtUptime(sec) {
  if (sec == null) return "";
  sec = Math.floor(sec);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return (h ? `${h}h ` : "") + `${m}m ${s}s`;
}

function appendLog(line) {
  const pre = $("log");
  const span = document.createElement("span");
  if (/ERROR|Traceback|예외|실패|error/i.test(line)) span.className = "err";
  else if (/상태 전이|\[bridge\]/.test(line)) span.className = "st";
  span.textContent = line + "\n";
  const stick = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 8;
  pre.appendChild(span);
  while (pre.childNodes.length > 400) pre.removeChild(pre.firstChild);
  if (stick) pre.scrollTop = pre.scrollHeight;
}

function renderStatus(st) {
  $("bridge").classList.add("on");
  $("ext").classList.toggle("on", !!st.ext);
  const b = st.bot || {};
  botRunning = !!b.running;
  const badge = $("botstate");
  if (b.running && b.stop_requested) { badge.className = "badge stopping"; badge.textContent = "중지 중 (" + (b.state || "…") + ")"; }
  else if (b.running) { badge.className = "badge on"; badge.textContent = b.state || "기동 중"; }
  else { badge.className = "badge off"; badge.textContent = b.exit == null ? "정지" : `정지 (exit ${b.exit})`; }
  $("uptime").textContent = b.running ? fmtUptime(b.uptime) + (b.pid ? `  pid ${b.pid}` : "") : "";
  $("last").textContent = b.last || "";
  $("start").disabled = b.running || !st.ext;
  $("stop").disabled = !b.running || b.stop_requested;
  $("kill").disabled = !b.running;
}

function renderOffline(reason) {
  $("bridge").classList.remove("on");
  $("ext").classList.remove("on");
  $("botstate").className = "badge off"; $("botstate").textContent = "브리지 없음";
  $("uptime").textContent = ""; $("last").textContent = reason || "ext_bridge.py 가 :9335 에서 실행 중이어야 합니다";
  ["start", "stop", "kill"].forEach((id) => { $(id).disabled = true; });
}

function send(cmd, extra = {}) {
  return new Promise((resolve, reject) => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return reject(new Error("브리지 연결 없음"));
    const id = ++nextId;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, cmd, ...extra }));
    setTimeout(() => { if (pending.delete(id)) reject(new Error(`${cmd} 응답 없음`)); }, 8000);
  });
}

function renderTabs(tabs) {
  const ul = $("tablist"); ul.innerHTML = "";
  if (!tabs.length) { const li = document.createElement("li"); li.textContent = "퍼플온 탭 없음 (purpleon.plaync.com 열기)"; ul.appendChild(li); return; }
  for (const t of tabs) {
    const li = document.createElement("li");
    li.className = t.attached ? "attached" : "";
    li.textContent = `${t.title || "(제목 없음)"} — ${t.url || ""}`;
    li.title = t.url || "";
    ul.appendChild(li);
  }
}

async function refreshTabs() {
  try { const r = await send("tabs"); renderTabs(r.tabs || []); }
  catch (e) { renderTabs([]); }
}

function connect() {
  try { ws = new WebSocket(UI_URL); } catch (e) { renderOffline(String(e)); return; }
  ws.onopen = () => { refreshTabs(); };
  ws.onclose = () => { renderOffline(); setTimeout(connect, 1500); };
  ws.onerror = () => { /* onclose 가 뒤따른다 */ };
  ws.onmessage = (ev) => {
    let msg; try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.id != null && pending.has(msg.id)) {
      const p = pending.get(msg.id); pending.delete(msg.id);
      if (msg.ok === false) p.reject(new Error(msg.error || "실패")); else p.resolve(msg);
      if (msg.type === "status") renderStatus(msg);
      return;
    }
    if (msg.type === "status") renderStatus(msg);
    else if (msg.type === "log") appendLog(msg.line);
    else if (msg.type === "log_snapshot") { $("log").textContent = ""; (msg.lines || []).forEach(appendLog); }
  };
}

$("start").onclick = async () => {
  const seconds = Number($("seconds").value) || undefined;
  const interval = Number($("interval").value) || undefined;
  try { await send("start", { seconds, interval }); localStorage.setItem("opts", JSON.stringify({ seconds, interval })); }
  catch (e) { toast("시작 실패: " + e.message); }
};
$("stop").onclick = async () => { try { await send("stop"); } catch (e) { toast("중지 실패: " + e.message); } };
$("kill").onclick = async () => {
  if (!confirm("봇 프로세스를 즉시 종료합니다. 귀환 없이 캐릭터가 필드에 남을 수 있습니다.")) return;
  try { await send("stop", { force: true }); } catch (e) { toast("강제 종료 실패: " + e.message); }
};
$("refreshTabs").onclick = refreshTabs;
$("clearLog").onclick = () => { $("log").textContent = ""; };

try {
  const o = JSON.parse(localStorage.getItem("opts") || "null");
  if (o) { if (o.seconds) $("seconds").value = o.seconds; if (o.interval) $("interval").value = o.interval; }
} catch {}
renderOffline();
connect();
