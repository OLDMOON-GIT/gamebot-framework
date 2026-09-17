#!/bin/bash
# GameBot 업데이트 — git pull 후 봇 재기동
cd "$(dirname "$0")"
echo "=== GameBot 업데이트 ==="
git pull
echo "=== 확장 리로드 ==="
python3 - << 'PYEOF'
from cdp_window import CdpWindow
import json, urllib.request, time, websocket
pages = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json"))
tab = next((p for p in pages if "extensions" in p.get("url","")), None)
if tab:
    ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=10)
    ws.send(json.dumps({"id":1, "method":"Runtime.evaluate", "params":{"expression":"""
(()=>{const mgr=document.querySelector('extensions-manager');
if(!mgr)return;
const items=mgr.shadowRoot.querySelectorAll('extensions-item');
for(const it of items){const btn=it.shadowRoot.querySelector('#dev-reload-button');
if(btn)btn.click();}})()""","returnByValue":True}}))
    print("확장 리로드 완료")
    ws.close()
PYEOF
echo "=== 봇 재기동 ==="
tmux kill-session -t linc-hunt 2>/dev/null
tmux kill-session -t linc-aden 2>/dev/null
rm -f /tmp/linc-bot-linux/stop /tmp/linc-bot-linux/stop-aden
tmux new-session -d -s linc-hunt "cd $(dirname $0) && python3 games/lineage_classic/hunt_bot.py >> /tmp/onestep_hunt.log 2>&1"
tmux new-session -d -s linc-aden "cd $(dirname $0) && python3 games/lineage_classic/picker.py >> /tmp/aden_picker.log 2>&1"
echo "✅ 업데이트 + 재기동 완료"
