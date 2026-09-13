# linc-bot 크롬 확장 브리지 (BTS-1033280)

크롬을 `--remote-debugging-port` 없이 띄워도 봇이 붙을 수 있게 하는 경로.

```
cycle_bot --ext ──ws──▶ ext_bridge.py(:9335) ◀──ws── 확장 서비스워커 ──chrome.debugger──▶ 퍼플 탭
```

- `ext_bridge.py` 는 크롬 원격 디버깅의 `/json`, `/json/version`, `/devtools/page/<id>` 를
  그대로 흉내낸다. 그래서 `CdpWindow(port=9335)` 가 코드 변경 없이 붙는다.
- 확장은 `purpleon.plaync.com` 탭에 `chrome.debugger.attach` 하고 CDP 명령을 중계한다.
  브리지가 죽어도 2초마다 재접속한다. 탭 URL 이 바뀌면 자동 detach.
- 봇별 `id` 는 브리지가 전역 id 로 재매핑하므로 봇 여러 개가 동시에 붙어도 응답이 섞이지 않는다.

## 설치

1. 브리지: `systemctl --user enable --now linc-ext-bridge.service` (이미 설치됨)
2. 확장:
   - 봇 전용 크롬(`run_bot_chrome.sh`)은 `--load-extension` 으로 자동 로드.
   - 일반 크롬은 `chrome://extensions` → 개발자 모드 → "압축해제된 확장 프로그램 로드" → 이 폴더.
   - 크롬 137+ 브랜드 빌드는 `--load-extension` 을 무시하므로 수동 로드가 필요.
3. 봇: `python3 cycle_bot.py --ext` (`--cdp` 대신)

## 확인

```
curl -s http://127.0.0.1:9335/json/version   # extensionConnected: true
curl -s http://127.0.0.1:9335/json           # 퍼플 탭 목록
python3 -m pytest test_ext_bridge.py -q      # 10 tests
```

## 주의

- `chrome.debugger` attach 중에는 탭 상단에 "디버깅 중" 띠가 뜬다.
  `--silent-debugger-extension-api` 플래그로 숨길 수 있다(봇 크롬에 적용됨).
- 같은 탭에 `--cdp`(9333 직결) 와 `--ext`(확장 경유) 를 동시에 붙이는 조합은 검증하지 않았다.
  한 탭에는 한 경로만 쓸 것.
