from item_tiers import tier_of


def test_아데나는_줍는다():
    assert tier_of("아데나") == "high"
    assert tier_of("아데나 1000") == "high"


def test_몽둥이는_쓰레기():
    assert tier_of("몽둥이") == "low"
    assert tier_of("나무몽둥이") == "low"
    assert tier_of("곤봉") == "low"


def test_주문서와_반지는_줍는다():
    assert tier_of("순간이동 주문서") == "high"
    assert tier_of("금반지") == "high"
