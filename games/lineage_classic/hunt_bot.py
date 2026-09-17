"""리니지 클래식 hunt_bot — 기존 파일 래핑."""
import sys, os
_base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _base)
from hunt_bot import *
