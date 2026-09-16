"""hunt_priority 한 틱 한 행동 (BTS-1033580)."""
from hunt_priority import (
    ATTACK, HOLD, MP_POTION, PICKUP, POTION1, POTION2, RETURN, SEARCH, STOP,
    TRANSFORM, decide,
)

S = {
    "enabled": True,
    "return_enabled": True,
    "danger_pct": 20,
    "return_key": "F8",
    "emergency_potion": {"key": "F6", "kind": "맑은"},
    "emergency_pct": 45,
    "main_potion": {"key": "F5", "kind": "주홍"},
    "potion_start_pct": 80,
    "mp_recover_enabled": True,
    "mp_potion": {"key": "F7", "kind": "mana"},
    "mp_start_pct": 30,
    "mp_emergency_pct": 15,
    "mp_return_enabled": True,
    "mp_return_pct": 10,
    "weight_return": True,
    "weight_return_pct": 80,
    "no_combat_return": True,
    "no_combat_sec": 600,
    "potion_empty_return": True,
    "pickup_enabled": True,
    "pickup_priority": False,
    "pickup_weight_enabled": True,
    "pickup_weight_pct": 70,
    "auto_attack": True,
    "shapechange": True,
    "transformKey": "F3",
    "antidote": True,
    "antidote_key": "F2",
}


def st(**kw):
    base = dict(window_ok=True, dead=False, hp=0.9, mp=0.9, weight=0.4,
                in_combat=False, mob_nearby=False, item_nearby=False)
    base.update(kw)
    return base


def test_봇끄면_대기():
    assert decide(st(), {**S, "enabled": False}).kind == HOLD


def test_창없으면_중지():
    assert decide(st(window_ok=False), S).kind == STOP


def test_사망이면_중지():
    assert decide(st(dead=True), S).kind == STOP


def test_HP없으면_대기():
    assert decide(st(hp=None), S).kind == HOLD


def test_HP귀환이_물약보다_앞선다():
    a = decide(st(hp=0.15), S)
    assert a.kind == RETURN and a.key == "F8" and "HP" in a.reason


def test_2차물약이_1차보다_앞선다():
    a = decide(st(hp=0.40), S)
    assert a.kind == POTION2 and a.key == "F6"


def test_1차물약_80퍼():
    a = decide(st(hp=0.70), S)
    assert a.kind == POTION1 and a.key == "F5"


def test_풀피면_물약안함():
    a = decide(st(hp=0.95, mob_nearby=True), S)
    assert a.kind == ATTACK


def test_MP귀환():
    a = decide(st(hp=0.9, mp=0.05), S)
    assert a.kind == RETURN and "MP" in a.reason


def test_무게귀환이_줍기보다_앞선다():
    a = decide(st(hp=0.9, weight=0.85, item_nearby=True), S)
    assert a.kind == RETURN and "무게" in a.reason


def test_비전투귀환():
    a = decide(st(hp=0.9, last_combat_age_sec=700), S)
    assert a.kind == RETURN and "비전투" in a.reason


def test_물약없음귀환():
    a = decide(st(hp=0.9, potions_empty=True), S)
    assert a.kind == RETURN and "물약" in a.reason


def test_MP회복():
    a = decide(st(hp=0.9, mp=0.20), S)
    assert a.kind == MP_POTION and a.key == "F7"


def test_전투중_줍기는_우선OFF면_안함():
    a = decide(st(hp=0.9, in_combat=True, item_nearby=True, mob_nearby=True), S)
    assert a.kind == ATTACK


def test_아이템우선ON이면_전투중에도_줍기():
    a = decide(st(hp=0.9, in_combat=True, item_nearby=True),
               {**S, "pickup_priority": True})
    assert a.kind == PICKUP


def test_획득무게초과면_줍기안함():
    a = decide(st(hp=0.9, weight=0.75, item_nearby=True, in_combat=False), S)
    assert a.kind != PICKUP


def test_변신갱신():
    a = decide(st(hp=0.9, transform_due=True), S)
    assert a.kind == TRANSFORM and a.key == "F3"


def test_획득무게제한OFF면_줍기가능():
    a = decide(st(hp=0.9, weight=0.95, item_nearby=True),
               {**S, "pickup_weight_enabled": False, "weight_return": False})
    assert a.kind == PICKUP


def test_탐색기본():
    a = decide(st(hp=0.9), S)
    assert a.kind == SEARCH


def test_HP정확히_20퍼면_귀환_경계():
    a = decide(st(hp=0.20), S)
    assert a.kind == RETURN and "HP" in a.reason


def test_HP가_20점1퍼면_물약경로():
    a = decide(st(hp=0.201), S)
    assert a.kind == POTION2 and a.key == "F6"


def test_MP귀환OFF면_MP5퍼여도_귀환안함():
    a = decide(st(hp=0.9, mp=0.05), {**S, "mp_return_enabled": False})
    assert a.kind != RETURN
    assert a.kind == MP_POTION and a.key == "F7"


def test_자동공격OFF면_몹있어도_탐색():
    a = decide(st(hp=0.9, mob_nearby=True), {**S, "auto_attack": False})
    assert a.kind == SEARCH


def test_줍기OFF면_아이템있어도_줍기아님():
    a = decide(st(hp=0.9, item_nearby=True), {**S, "pickup_enabled": False})
    assert a.kind != PICKUP
    assert a.kind == SEARCH
