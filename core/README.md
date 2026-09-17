# GameBot Framework

## 구조
```
core/                    # 게임 공용 코어
├── cdp_window.py       # CDP 창 제어 (캡처/클릭/키)
├── potion.py           # 물약 시스템 (주/보조/귀환)
├── settings.py         # 설정 (JSON + HTTP API)
├── user_gate.py        # 사용자 입력 양보
├── ext_receiver.py     # 확장 HUD 수신기 (HTTP)
├── ext_bridge.py       # chrome.debugger 브리지

games/
└── lineage_classic/    # 리니지 클래식 프로필
    ├── vision.py       # HP/캐릭터/몹 판독
    ├── hunt_bot.py     # 사냥 봇
    ├── picker.py       # 줍기 봇
    ├── item_*.py       # 아이템 판별
    └── chat_watch.py   # 채팅 감시

extension/              # 크롬 확장 (모든 게임 공용)
linc-vision-ext/        # 비전 확장 (모든 게임 공용)
```

## 다른 게임 추가
1. `games/<게임명>/` 폴더 생성
2. vision.py에 HP/캐릭터/몹 판독 구현
3. hunt_bot.py에서 core 모듈 import해 봇 작성
4. 필요한 rect/상수를 게임별 config로

## 업데이트
```bash
cd ~/workspace/linc-bot
git pull                    # 코어+게임 전체 업데이트
# 또는 코어만
git pull origin master -- core/
```

## 다른 프로젝트에서 사용
```python
import sys; sys.path.insert(0, "/home/oldmoon/workspace/linc-bot")
from core.cdp_window import CdpWindow, EXT_PORT
from core.potion import PotionKeys
from core.settings import load, save

w = CdpWindow(port=EXT_PORT)
potion = PotionKeys()
img = w.capture()
hp = my_game_hp_reader(img)  # 게임별 구현
result = potion.check(w, hp)
```

## 크롬 확장 업데이트
- `chrome://extensions` → 개발자 모드 → 리로드 버튼
- 또는 코드에서 확장 리로드 자동화
