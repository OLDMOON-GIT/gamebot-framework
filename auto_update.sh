#!/bin/bash
# GameBot 자동 업데이트 — cron/systemd로 주기 실행
# 사용법:
#   ./auto_update.sh              # 1회 체크
#   ./auto_update.sh --daemon     # 백그라운드 5분마다 체크
#   ./auto_update.sh --install    # systemd 타이머 등록 (자동 시작)

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="/tmp/gamebot_update.log"
INTERVAL=300  # 5분

check_and_update() {
  cd "$DIR"
  # 원격에 새 커밋 있는지 확인 (fetch만)
  git fetch origin master --quiet 2>/dev/null
  LOCAL=$(git rev-parse HEAD)
  REMOTE=$(git rev-parse origin/master)
  
  if [ "$LOCAL" != "$REMOTE" ]; then
    echo "$(date +%H:%M:%S) 업데이트 발견: $LOCAL → $REMOTE" >> "$LOG"
    git pull --quiet
    
    # 확장 리로드
    python3 - << 'PYEOF' >> "$LOG" 2>&1
try:
    import json, urllib.request, websocket
    pages = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json", timeout=3))
    tab = next((p for p in pages if "extensions" in p.get("url","")), None)
    if tab:
        ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=10)
        ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":
          "(()=>{const m=document.querySelector('extensions-manager');if(!m)return;"+
          "m.shadowRoot.querySelectorAll('extensions-item').forEach(it=>{"+
          "const b=it.shadowRoot.querySelector('#dev-reload-button');if(b)b.click()})})()",
          "returnByValue":True}}))
        print("  확장 리로드 완료")
        ws.close()
except Exception as e:
    print(f"  확장 리로드 실패: {e}")
PYEOF
    
    # 봇 재기동 (게임이 점검 중이 아닐 때만)
    if ! grep -q "점검" /tmp/game_state.txt 2>/dev/null; then
      tmux kill-session -t linc-hunt 2>/dev/null
      tmux kill-session -t linc-aden 2>/dev/null
      rm -f /tmp/linc-bot-linux/stop /tmp/linc-bot-linux/stop-aden
      tmux new-session -d -s linc-hunt "cd $DIR && python3 onestep_hunt.py >> /tmp/onestep_hunt.log 2>&1"
      tmux new-session -d -s linc-aden "cd $DIR && python3 aden_picker.py >> /tmp/aden_picker.log 2>&1"
      echo "  봇 재기동 완료" >> "$LOG"
    else
      echo "  게임 점검 중 — 봇 재기동 보류" >> "$LOG"
    fi
    
    # 텔레그램 알림 (선택)
    if [ -f /home/oldmoon/workspace/.env ]; then
      source /home/oldmoon/workspace/.env 2>/dev/null
      if [ -n "$TG_TOKEN" ]; then
        MSG="🎮 GameBot 업데이트 완료%0A$(git log --oneline -3 | head -3 | sed 's/#/%23/g' | tr '\n' '%0A')"
        curl -s --max-time 5 "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
          -d "chat_id=${TG_CHAT_ID:-$(cat /tmp/tg_chat_id 2>/dev/null || echo '')}" \
          -d "text=${MSG}" > /dev/null 2>&1
      fi
    fi
    
    echo "$(date +%H:%M:%S) ✅ 자동 업데이트 완료" >> "$LOG"
  else
    echo "$(date +%H:%M:%S) 최신 버전 유지 중" >> "$LOG"
  fi
}

case "${1:-}" in
  --daemon)
    echo "$(date +%H:%M:%S) 자동 업데이트 데몬 시작 (${INTERVAL}s 간격)" >> "$LOG"
    while true; do
      check_and_update
      sleep "$INTERVAL"
    done
    ;;
  --install)
    # systemd user 타이머 등록
    mkdir -p ~/.config/systemd/user
    cat > ~/.config/systemd/user/gamebot-update.service << SVC
[Unit]
Description=GameBot Auto Update

[Service]
Type=oneshot
ExecStart=${DIR}/auto_update.sh
SVC
    cat > ~/.config/systemd/user/gamebot-update.timer << TMR
[Unit]
Description=GameBot Auto Update Timer

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
TMR
    systemctl --user daemon-reload
    systemctl --user enable gamebot-update.timer
    systemctl --user start gamebot-update.timer
    echo "✅ systemd 타이머 등록 완료 (5분마다 자동 업데이트 체크)"
    systemctl --user status gamebot-update.timer --no-pager | head -5
    ;;
  *)
    check_and_update
    cat "$LOG" | tail -5
    ;;
esac
