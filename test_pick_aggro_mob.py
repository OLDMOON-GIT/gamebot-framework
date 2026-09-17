from onestep_hunt import pick_aggro_mob


def test_가까운_몹을_선빵으로_고른다():
    char = (100, 100)
    far = (250, 100, 5000)
    near = (130, 100, 200)
    got = pick_aggro_mob([far, near], char)
    assert got == near


def test_이미_찍은_타겟을_유지한다():
    char = (100, 100)
    a = (140, 100, 100)
    b = (120, 100, 100)
    got = pick_aggro_mob([a, b], char, last_xy=(142, 98))
    assert got == a
