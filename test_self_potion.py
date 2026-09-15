"""직접 물약 투입(생존 최후수단) 테스트.

배경: 물약 소유권을 공식 ATS에 위임했으나 ats_setup_clicks가 비어 있으면
아무도 물약을 먹지 않아 캐릭터가 죽는다. HP 판독 실패 구간도 무방비였다.
"""
import time

import cycle_bot


class FakeWindow:
    def __init__(self):
        self.keys = []

    def geometry(self):
        return (0, 0, 1933, 1332)

    def key(self, name, expected_geometry):
        self.keys.append(name)


def make_bot(cfg=None):
    bot = object.__new__(cycle_bot.CycleBot)
    bot.cfg = {"potion_hp": 0.75, "potion_key": "F5", "potion_cooldown_s": 3.0,
               "hp_unknown_potion_streak": 3}
    if cfg:
        bot.cfg.update(cfg)
    bot.window = FakeWindow()
    bot.stats = {}
    bot._last_self_potion = None
    bot._hp_unknown_streak = 0
    bot.wait_user_idle = lambda: None
    return bot


def test_저HP면_물약키를_누른다():
    bot = make_bot()
    assert bot.self_potion(0.70, "저HP") is True
    assert bot.window.keys == ["F5"]
    assert bot.stats["self_potions"] == 1


def test_쿨다운_안에서는_중복투입하지_않는다():
    bot = make_bot()
    assert bot.self_potion(0.70, "저HP") is True
    assert bot.self_potion(0.69, "저HP") is False
    assert bot.window.keys == ["F5"]


def test_쿨다운_지나면_다시_투입한다():
    bot = make_bot({"potion_cooldown_s": 0.0})
    assert bot.self_potion(0.70, "저HP") is True
    bot._last_self_potion = time.monotonic() - 5
    assert bot.self_potion(0.70, "저HP") is True
    assert bot.window.keys == ["F5", "F5"]


def test_판독불가여도_예외없이_투입한다():
    bot = make_bot()
    assert bot.self_potion(None, "HP 판독 연속 실패") is True
    assert bot.window.keys == ["F5"]


def test_키입력_실패는_삼키고_재시도를_남긴다():
    bot = make_bot()

    def boom(name, geo):
        raise RuntimeError("창 소실")

    bot.window.key = boom
    assert bot.self_potion(0.70, "저HP") is False
    assert bot.stats.get("self_potions") is None
    assert bot._last_self_potion is None  # 쿨다운을 먹지 않아 즉시 재시도 가능


def test_설정된_물약키를_따른다():
    bot = make_bot({"potion_key": "F6"})
    assert bot.self_potion(0.10, "저HP") is True
    assert bot.window.keys == ["F6"]
