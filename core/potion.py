"""GameBot 물약 시스템 — 게임 공용 (potion_keys.py 래핑)."""
import sys, os
_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _base)
from potion_keys import *
