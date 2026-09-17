#!/bin/bash
set -e
# GameBot Framework 원라인 설치
# 사용법: curl -fsSL https://raw.githubusercontent.com/OLDMOON-GIT/gamebot-framework/master/install.sh | bash

echo "🎮 GameBot Framework 설치 시작"
echo "=============================="

# 의존성
echo "📋 의존성 설치..."
sudo apt-get update -qq && sudo apt-get install -y -qq \
  python3 python3-pip python3-opencv tesseract-ocr tesseract-ocr-kor \
  chromium-browser xvfb tmux 2>/dev/null || true

pip3 install --user opencv-python-headless numpy websocket-client 2>/dev/null || \
  pip3 install --break-system-packages opencv-python-headless numpy websocket-client

# 클론
INSTALL_DIR="$HOME/gamebot"
if [ -d "$INSTALL_DIR" ]; then
  echo "📦 기존 설치 업데이트..."
  cd "$INSTALL_DIR" && git pull
else
  echo "📦 저장소 클론..."
  git clone git@github.com:OLDMOON-GIT/gamebot-framework.git "$INSTALL_DIR" \
    || git clone https://github.com/OLDMOON-GIT/gamebot-framework.git "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi

# 자동 업데이트 설치 (5분마다)
./auto_update.sh --install

echo ""
echo "✅ 설치 완료!"
echo "=============================="
echo "📁 위치: $INSTALL_DIR"
echo "🚀 실행: python3 $INSTALL_DIR/run.py all"
echo "🔄 업데이트: 자동 (5분마다 체크)"
echo "📊 로그: tail -f /tmp/onestep_hunt.log"
echo ""
echo "설정 (~/.gamebot/config.json):"
mkdir -p ~/.gamebot
cat > ~/.gamebot/config.json << CONFIG
{
  "telegram_token": "여기에_텔레그램_봇_토큰",
  "telegram_chat_id": "여기에_채팅_ID",
  "license_key": "여기에_라이선스_키"
}
CONFIG
echo "  텔레그램 알림을 받으려면 위 파일을 편집하세요."
