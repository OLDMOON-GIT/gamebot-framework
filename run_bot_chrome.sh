#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 한/영 입력기(fcitx5) 연결 — 이 환경변수가 없으면 크롬이 입력기에 붙지 못해 한영키가 먹지 않음
# GTK3 모듈명은 반드시 fcitx5. 'fcitx'로 두면 모듈이 없어 XIM으로 폴백되고,
# XIM은 fcitx 비활성(-c)을 무시해 한글→영문 복귀가 안 된다(검증: gedit 왕복 테스트).
export GTK_IM_MODULE=fcitx5
export QT_IM_MODULE=fcitx5
export XMODIFIERS=@im=fcitx
export CLUTTER_IM_MODULE=fcitx
# 크로미움은 입력기에 "세션 D-Bus"로 붙는다. tmux/서비스에서 뜨면 이 주소가 없어
# 위 IM 변수들이 있어도 IME 연결이 안 되고 한영키가 영문으로 통과한다(BTS-1032722 후속).
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"

# ── 디스플레이 자동 탐지 (BTS: 아덴 줍기 먹통 근본원인) ──────────────────
# 과거엔 DISPLAY=:0 하드코딩이었으나 이 PC의 실제 데스크톱은 Xwayland :1 이라
# 크롬이 "Missing X server or $DISPLAY"로 즉시 죽고 while 루프가 4초마다
# 재시도하는 무한 크래시 루프가 됐다. → CDP 9333이 한 번도 안 떠서
# cdp_window/aden_picker/cycle_bot이 게임에 붙지 못했다(= 아덴 줍기 불가).
# 실제로 창이 존재하는(= 로그인된 데스크톱) 디스플레이를 골라 쓴다.
pick_display() {
  local cand
  for cand in ${LINC_DISPLAY:-} :1 :0 $(ls /tmp/.X11-unix/ 2>/dev/null | sed 's/^X/:/'); do
    [ -z "$cand" ] && continue
    if DISPLAY="$cand" xdpyinfo >/dev/null 2>&1; then
      # 창 매니저가 붙어있는(진짜 데스크톱) 디스플레이 우선
      if DISPLAY="$cand" wmctrl -m >/dev/null 2>&1; then echo "$cand"; return 0; fi
      : "${fallback:=$cand}"
    fi
  done
  [ -n "${fallback:-}" ] && { echo "$fallback"; return 0; }
  return 1
}

fails=0
while true; do
  DISP="$(pick_display)" || DISP=":1"
  export DISPLAY="$DISP"
  echo "[$(date '+%F %T')] 기동: DISPLAY=$DISPLAY (연속실패 $fails)" \
    >> /home/oldmoon/workspace/linc-bot/botchrome.log
  start_ts=$(date +%s)
  # fcitx5가 떠 있지 않으면 먼저 기동
  pgrep -x fcitx5 >/dev/null || (setsid fcitx5 -d >/dev/null 2>&1 &)
  # 강제 종료 후 재기동하면 크롬이 이전 세션 탭을 복원해 퍼플온 탭이 2개가 되고
  # cdp_window 가 "탭을 하나로 특정할 수 없음"으로 죽는다(실측). 9333이 뜨면 중복 탭·
  # 단축키 안내 탭(support.google.com)을 닫아 퍼플온 탭 하나만 남긴다.
  ( for _ in $(seq 1 40); do sleep 1
      curl -sf http://127.0.0.1:9333/json >/dev/null 2>&1 || continue
      python3 - <<'PY' >> /home/oldmoon/workspace/linc-bot/botchrome.log 2>&1
import json, urllib.request
ts = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json", timeout=3))
keep = False
for t in ts:
    u = t.get("url", "")
    if t.get("type") != "page":
        continue
    dup = "purpleon.plaync.com/webplay" in u and keep
    junk = "support.google.com" in u
    if "purpleon.plaync.com/webplay" in u:
        keep = True
    if dup or junk:
        urllib.request.urlopen(f"http://127.0.0.1:9333/json/close/{t['id']}", timeout=3).read()
        print(f"기동 정리: 탭 닫음 {'중복 퍼플온' if dup else '안내'} {u[:60]}")
PY
      break
    done ) &
  /home/oldmoon/.cache/ms-playwright/chromium-1234/chrome-linux/chrome \
    --remote-debugging-port=9333 --remote-allow-origins='*' \
    --load-extension="$SCRIPT_DIR/extension,$SCRIPT_DIR/linc-vision-ext" --silent-debugger-extension-api \
    --user-data-dir=/home/oldmoon/.purpleon-profile \
    --disable-backgrounding-occluded-windows \
    --disable-features=CalculateNativeWinOcclusion \
    --use-gl=swiftshader --use-angle=swiftshader \
    --force-device-scale-factor=1 --no-sandbox \
    --no-first-run --no-default-browser-check --password-store=basic \
    --window-size=2210,1552 --window-position=0,0 \
    'https://purpleon.plaync.com/webplay/linclassic' >> /home/oldmoon/workspace/linc-bot/botchrome.log 2>&1
  # 즉시 죽으면(=환경 문제) 백오프. 무한 크래시 루프로 CPU/로그를 태우지 않는다.
  if [ $(( $(date +%s) - start_ts )) -lt 15 ]; then
    fails=$((fails + 1))
    backoff=$(( fails * 10 )); [ $backoff -gt 300 ] && backoff=300
    echo "[$(date '+%F %T')] 크롬이 ${fails}회 연속 즉시 종료 — ${backoff}s 대기 (DISPLAY=$DISPLAY 확인 필요)" \
      >> /home/oldmoon/workspace/linc-bot/botchrome.log
    sleep "$backoff"
  else
    fails=0
    sleep 4
  fi
done
