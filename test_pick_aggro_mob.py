from onestep_hunt import MELEE_RADIUS, pick_aggro_mob, should_hold_swing


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
    assert pick_aggro_mob([far, melee], char, last_xy=far[:2]) == melee


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

