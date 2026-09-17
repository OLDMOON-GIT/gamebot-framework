"""리니지 클래식 chat_watch — 기존 파일 래핑."""
import sys, os
_base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _base)
from chat_watch import *
