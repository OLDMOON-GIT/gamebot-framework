"""사던4층만 사냥, 버땅/축복의땅 스킵."""
import time

from hunt_zone import HuntZone, classify_map, is_forbidden_mob, read_map_name
from onestep_hunt import kill_rank, pick_aggro_mob


def test_사던4층은_허용():
    assert classify_map("사막 던전 4층") == "allow"
    assert classify_map("막 던전 4층") == "allow"
    assert classify_map("사막던전4층") == "allow"


def test_버땅은_스킵():
    assert classify_map("버림받은 자들의 땅") == "skip"
    assert classify_map("버땅") == "skip"
    assert classify_map("버림받은자들의땅") == "skip"


def test_축복의땅은_스킵():
    assert classify_map("축복의 땅") == "skip"
    assert classify_map("타락한 축복의 땅") == "skip"
    assert classify_map("축복의땅") == "skip"


def test_스킵이_허용보다_우선():
    assert classify_map("사막 던전 옆 축복의 땅") == "skip"


def test_빈값_미확인():
    assert classify_map("") == "unknown"
    assert classify_map(None) == "unknown"
    assert classify_map("화전민 마을") == "unknown"


def test_버그베어는_사던버그_아님():
    assert is_forbidden_mob("버그베어")
    assert is_forbidden_mob("Bugbear")
    assert not is_forbidden_mob("버그")
    assert not is_forbidden_mob("킹버그")
    assert kill_rank("버그베어") > kill_rank("버그")
    assert kill_rank("켈베로스") < kill_rank("버그")


def test_버그베어는_타겟에서_제외():
    char = (0, 0)
    bear = (10, 0, 10, "버그베어")
    bug = (80, 0, 10, "버그")
    got = pick_aggro_mob([bear, bug], char)
    assert got[3] == "버그"
    assert pick_aggro_mob([bear], char) is None


def test_헌트존_스킵_고정():
    z = HuntZone(default="allow")
    z.last_name = "사막 던전 4층"
    z.last = "allow"
    z._at = time.monotonic()
    kind, name = z.decide(None)
    assert kind == "allow"
    z.last = "skip"
    z.last_name = "버림받은 자들의 땅"
    z._at = time.monotonic()
    kind, name = z.decide(None)
    assert kind == "skip"
    assert "버림받은" in name


def test_실측프레임_사던4층():
    import os
    import cv2
    path = "/tmp/linc-now.png"
    if not os.path.exists(path):
        return
    img = cv2.imread(path)
    if img is None:
        return
    text = read_map_name(img)
    assert classify_map(text) == "allow", text
    assert "던전" in text or "4층" in text or "사막" in text, text
