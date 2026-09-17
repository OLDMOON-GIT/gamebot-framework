#!/usr/bin/env python3
"""GameBot 확장 수신기 — HTTP 서버 (모든 게임 공용).

확장이 보내는 HUD 프레임을 수신하고 /hp, /bot-settings API 제공.
"""
# 기존 ext_vision.py 로직을 그대로 사용
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
exec(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ext_vision.py')).read())
