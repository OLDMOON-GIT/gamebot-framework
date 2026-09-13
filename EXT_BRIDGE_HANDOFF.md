# 크롬 확장 브리지 인수인계 (GLM 용)

봇의 게임 창 제어(캡처·클릭·키 입력)가 `--remote-debugging-port=9333` 직결에서
**크롬 확장(chrome.debugger) 경유**로 바뀌었다. 코드는 커밋됨(BTS-1033280).

## 구조

```
cycle_bot / onestep_hunt / aden_picker
        │  CdpWindow(port=EXT_PORT)   # EXT_PORT=9335
        ▼
ext_bridge.py  (systemd --user linc-ext-bridge.service, 127.0.0.1:9335)
   /json, /json/version            ← 기존 9333 과 같은 모양(호환)
   /devtools/page/<id>  (봇 쪽 ws) ← Origin 없는 접속만 수락
   /ext                 (확장 ws)  ← Origin=chrome-extension:// 만 수락
        ▲
extension/  (background.js, MV3 서비스워커, chrome.debugger.attach)
        ▲
크롬  --load-extension=extension,linc-vision-ext  (run_bot_chrome.sh 가 이미 넣음)
```

- 봇 코드는 **`CdpWindow(port=EXT_PORT)`** 한 줄만 바꾸면 된다. 메서드(`send`,
  `capture`, `click`, `key`, `active` …)는 9333 직결과 동일하다.
- 9333 직결도 그대로 살아있다. 실패 시 `CdpWindow(port=9333)` 으로 되돌리면 된다.
- `linc-vision-ext`(GLM 이 만든 content-script 캡처 → 17311 POST) 는 **그대로 병행
  로드된다.** 두 확장은 서로 간섭하지 않는다(하나는 chrome.debugger, 하나는 canvas).
  단 `chrome.debugger` 가 붙어있는 탭에서 content-script 캡처가 필요하면 그대로 쓰고,
  **입력(클릭/키)은 ext_bridge 쪽만 쓴다** — 두 경로로 입력을 동시에 넣지 말 것.

## 확인 방법

```bash
curl -s http://127.0.0.1:9335/json/version     # "extensionConnected": true 이어야 함
curl -s http://127.0.0.1:9335/json             # 퍼플온 탭 1개
python3 -c "from cdp_window import CdpWindow, EXT_PORT; w=CdpWindow(port=EXT_PORT); print(w.capture().shape); w.close()"
#   → (1332, 1933, 3)
python3 -m pytest test_ext_bridge.py -q         # 12 passed
```

## 주의 (실측된 함정)

1. **크롬을 강제 종료 후 재기동하면 이전 세션 탭이 복원돼 퍼플온 탭이 2개** 가 되고
   `CdpWindow` 가 탭 특정 실패로 죽는다. `run_bot_chrome.sh` 가 기동 직후 중복 탭·
   support.google.com 안내 탭을 닫도록 고쳤다. 지금 떠 있는 루프는 고치기 전에
   시작된 것이라 다음 루프 재시작부터 적용된다.
2. 브리지는 Origin 을 검사한다. 웹페이지 JS 나 `Origin` 헤더를 가진 접속은 403.
   파이썬 `websockets` 는 기본으로 Origin 을 안 보내므로 그냥 붙는다.
3. `ext_bridge.service` 는 `StartLimitBurst=5/60s`. 9335 포트를 다른 게 잡고 있으면
   5회 실패 후 멈추니 `systemctl --user status linc-ext-bridge` 로 확인.
4. 확장은 `--silent-debugger-extension-api` 플래그가 있어야 "디버깅 중" 노란 바가
   안 뜬다. 런처에 이미 들어있다. 크롬을 손으로 띄울 때 빠뜨리지 말 것.

## 남은 일 (GLM 이 이어서 할 것)

- `cycle_bot.py`, `onestep_hunt.py`, `aden_picker.py` 의 `CdpWindow(...)` 생성부를
  `port=EXT_PORT` 로 전환 (현재는 9333 기본값). 전환 후 `test_cycle_bot.py` 통과 확인.
- `linc-vision-ext` 의 캡처와 `CdpWindow.capture()` 중 하나로 통일할지 결정.
  (chrome.debugger `Page.captureScreenshot` 은 창이 가려져도 찍힌다 — 이게 장점.)
