from types import SimpleNamespace

from aden_picker import NEAR_BOX_RADIUS, two_tile_highs


def test_두칸_안_아데나만_고른다():
    char = (1000, 600, 10, 10)
    aden = SimpleNamespace(name="아데나", click=(1000 + 400, 600))
    club = SimpleNamespace(name="몽둥이", click=(1000 + 50, 600))
    far = SimpleNamespace(name="아데나", click=(1000 + 800, 600))
    got = two_tile_highs(char, [aden, club, far])
    assert len(got) == 1
    assert got[0][3] == "아데나"
    assert got[0][0] <= NEAR_BOX_RADIUS ** 2


def test_저급만_있으면_빈목록():
    char = (500, 500, 1, 1)
    club = SimpleNamespace(name="몽둥이", click=(520, 500))
    assert two_tile_highs(char, [club]) == []
