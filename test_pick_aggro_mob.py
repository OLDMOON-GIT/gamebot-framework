from onestep_hunt import (
    MELEE_RADIUS, hunt_radius, kill_rank, pick_aggro_mob, should_hold_swing,
)


def test_사던4_킬순서():
    assert kill_rank("켈베로스") < kill_rank("킹버그") < kill_rank("버그")
    assert kill_rank("웰베로스") == kill_rank("켈베로스")
    char = (0, 0)
    bug = (40, 0, 10, "버그")
    king = (80, 0, 10, "킹버그")
    cerb = (200, 0, 10, "켈베로스")
    got = pick_aggro_mob([bug, king, cerb], char)
    assert got[3] == "켈베로스"
    got = pick_aggro_mob([bug, king], char)
    assert got[3] == "킹버그"


def test_탐색10칸은_화면범위():
    assert hunt_radius({"search_range": 10}) == 800
    assert hunt_radius({"search_range": 1}) == MELEE_RADIUS


def test_붙어있는_선빵몹을_먼몹보다_먼저_고른다():
    char = (100, 100)
    far = (100 + MELEE_RADIUS + 40, 100, 9000)
    melee = (100 + 40, 100, 100)
    got = pick_aggro_mob([far, melee], char)
    assert got == melee


def test_선빵이_있으면_먼몹은_고르지_않는다():
    char = (0, 0)
    melee = (50, 0, 10)
    far = (200, 0, 9999)
    assert pick_aggro_mob([far, melee], char) == melee


def test_이미_찍은_타겟을_유지한다():
    char = (100, 100)
    a = (140, 100, 100)
    b = (120, 100, 100)
    got = pick_aggro_mob([a, b], char, last_xy=(142, 98))
    assert got == a


def test_노란막대_붙은_몹이_선빵():
    char = (100, 100)
    a = (220, 100, 100)
    b = (240, 100, 100)
    bars = [(221, 70, 40)]
    got = pick_aggro_mob([a, b], char, bars=bars)
    assert got == a


def test_선빵_타겟이_있으면_홀드한다():
    last = (200, 200)
    mobs = [(205, 198, 100), (400, 400, 100)]
    assert should_hold_swing(None, 0, 999, last, mobs) is True
    assert should_hold_swing(None, None, 999, last, [(500, 500, 1)]) is False

