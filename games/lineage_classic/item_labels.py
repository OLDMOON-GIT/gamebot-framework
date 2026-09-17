"""리니지 클래식 item_labels — 기존 파일 래핑."""
import sys, os
_base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _base)
from item_labels import *
