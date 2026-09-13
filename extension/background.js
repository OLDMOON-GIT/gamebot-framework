// linc-bot bridge — MV3 service worker (BTS-1033280)
//
// 역할: 로컬 브리지(ext_bridge.py, ws://127.0.0.1:9335/ext)에 붙어서
// {id, method, params, tabId?} 를 받으면 퍼플온 탭에 chrome.debugger 로
// attach 한 뒤 sendCommand 로 실행하고 {id, result|error} 를 돌려준다.
// 디버거 이벤트는 {method, params} 로 그대로 흘려보낸다(브리지가 봇에 중계).
//
// 이렇게 하면 크롬을 --remote-debugging-port 로 띄울 필요가 없다. 사용자가
// 평소 쓰는 크롬에 이 확장만 올리면 기존 Python 봇(cdp_window.CdpWindow)이
// 포트만 바꿔 그대로 붙는다.

const BRIDGE_URL = "ws://127.0.0.1:9335/ext";
const TAB_URL_PATTERN = "https://purpleon.plaync.com/*";
const PROTOCOL_VERSION = "1.3";
const RECONNECT_MS = 2000;
const ALARM_NAME = "linc-bridge-keepalive";

let ws = null;
let attachedTabId = null;
let reconnectTimer = null;

function log(...args) {
  console.log("[linc-bridge]", ...args);
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  }
}

async function purpleTabs() {
  const tabs = await chrome.tabs.query({ url: TAB_URL_PATTERN });
  return tabs.map((t) => ({ id: t.id, url: t.url || "", title: t.title || "" }));
}

async function pickTab(requestedTabId) {
  const tabs = await purpleTabs();
  if (requestedTabId != null) {
    // 리뷰: 브리지가 준 tabId 라도 퍼플온 탭일 때만 attach 한다 (임의 탭 디버거 부착 차단)
    if (tabs.some((t) => t.id === requestedTabId)) {
      return requestedTabId;
    }
    throw new Error(`tabId ${requestedTabId} 는 퍼플온 탭이 아닙니다`);
  }
  if (tabs.length !== 1) {
    throw new Error(`퍼플온 탭을 하나로 특정할 수 없습니다: ${tabs.length}개`);
  }
  return tabs[0].id;
}

async function ensureAttached(tabId) {
  if (attachedTabId === tabId) {
    return;
  }
  if (attachedTabId != null) {
    try {
      await chrome.debugger.detach({ tabId: attachedTabId });
    } catch (_) {
      // 이미 떨어진 상태 — 무시
    }
    attachedTabId = null;
  }
  await chrome.debugger.attach({ tabId }, PROTOCOL_VERSION);
  attachedTabId = tabId;
  log("attached", tabId);
}

async function handle(msg) {
  const { id, method, params, tabId } = msg;
  try {
    if (method === "Bridge.ping") {
      return { id, result: { pong: true, attachedTabId } };
    }
    if (method === "Bridge.tabs") {
      return { id, result: { tabs: await purpleTabs() } };
    }
    if (method === "Bridge.detach") {
      if (attachedTabId != null) {
        await chrome.debugger.detach({ tabId: attachedTabId });
        attachedTabId = null;
      }
      return { id, result: {} };
    }
    const target = await pickTab(tabId);
    await ensureAttached(target);
    const result = await chrome.debugger.sendCommand({ tabId: target }, method, params || {});
    return { id, result: result || {} };
  } catch (err) {
    // chrome.debugger 오류는 chrome.runtime.lastError 문자열 또는 Error
    const message = (err && err.message) || String(err);
    return { id, error: { code: -32000, message } };
  }
}

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  try {
    ws = new WebSocket(BRIDGE_URL);
  } catch (err) {
    scheduleReconnect();
    return;
  }
  ws.onopen = () => {
    log("bridge 연결");
    send({ method: "Bridge.hello", params: { version: chrome.runtime.getManifest().version } });
  };
  ws.onmessage = async (ev) => {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch (_) {
      return;
    }
    if (msg && msg.id != null && msg.method) {
      send(await handle(msg));
    }
  };
  ws.onclose = () => {
    log("bridge 끊김");
    ws = null;
    scheduleReconnect();
  };
  ws.onerror = () => {
    // onclose 가 뒤따른다
  };
}

function scheduleReconnect() {
  if (reconnectTimer) {
    return;
  }
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, RECONNECT_MS);
}

chrome.debugger.onEvent.addListener((source, method, params) => {
  if (source.tabId === attachedTabId) {
    send({ method, params: params || {} });
  }
});

chrome.debugger.onDetach.addListener((source, reason) => {
  if (source.tabId === attachedTabId) {
    log("detached", reason);
    attachedTabId = null;
  }
});

// MV3 서비스워커는 유휴 시 내려간다. 알람으로 주기적으로 깨워 재접속한다.
chrome.alarms.create(ALARM_NAME, { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) {
    connect();
  }
});
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
connect();
