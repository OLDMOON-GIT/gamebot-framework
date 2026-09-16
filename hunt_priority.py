"""사냥 한 틱에 행동 하나. HUD 설정을 실제 우선순위로 바꾼다 (BTS-1033580).

1 사망/창없음  2 HP귀환  3 MP귀환  4 무게귀환  5 비전투귀환
6 2차물약  7 1차물약  8 MP회복  9 해독  10 기능아이템
11 공격마법  12 줍기  13 버프  14 변신  15 공격  16 탐색
"""
from dataclasses import dataclass

HOLD = "hold"
STOP = "stop"
RETURN = "return"
POTION2 = "potion2"
POTION1 = "potion1"
MP_POTION = "mp_potion"
ANTIDOTE = "antidote"
FUNC_ITEM = "func_item"
SKILL = "skill"
PICKUP = "pickup"
BUFF = "buff"
TRANSFORM = "transform"
ATTACK = "attack"
SEARCH = "search"


@dataclass(frozen=True)
class Action:
    kind: str
    reason: str = ""
    key: str = ""
    extra: object = None


def _on(s, name, default=False):
    v = s.get(name)
    if v is None:
        return default
    return bool(v)


def _pct(s, name, default):
    try:
        return float(s.get(name, default)) / 100.0
    except (TypeError, ValueError):
        return default / 100.0


def _key(slot, fallback=""):
    if isinstance(slot, dict):
        return slot.get("key") or fallback
    return fallback


def decide(state, settings):
    """state: hp/mp/weight(0~1 or None), window_ok, dead, enabled,
    poisoned, transformed, in_combat, last_combat_age_sec,
    potions_empty, item_nearby, buff_due, transform_due.
    """
    s = settings or {}
    if not _on(s, "enabled", True):
        return Action(HOLD, "봇 비활성")
    if not state.get("window_ok", True):
        return Action(STOP, "게임창 없음")
    if state.get("dead"):
        return Action(STOP, "캐릭터 사망")

    hp = state.get("hp")
    mp = state.get("mp")
    weight = state.get("weight")

    if hp is None:
        return Action(HOLD, "HP 인식 실패")

    if _on(s, "return_enabled", True) and hp <= _pct(s, "danger_pct", 20):
        return Action(RETURN, "HP 비상 귀환", s.get("return_key") or "F8")

    if _on(s, "mp_return_enabled", False) and mp is not None \
            and mp <= _pct(s, "mp_return_pct", 10):
        return Action(RETURN, "MP 귀환", s.get("return_key") or "F8")

    if _on(s, "weight_return", True) and weight is not None \
            and weight >= _pct(s, "weight_return_pct", 80):
        return Action(RETURN, "무게 귀환", s.get("return_key") or "F8")

    idle = state.get("last_combat_age_sec")
    idle_lim = s.get("no_combat_sec")
    if idle_lim is None and s.get("no_combat_minutes") is not None:
        idle_lim = float(s["no_combat_minutes"]) * 60
    if _on(s, "no_combat_return", False) and idle is not None and idle_lim \
            and idle >= float(idle_lim):
        return Action(RETURN, "비전투 귀환", s.get("return_key") or "F8")

    if state.get("potions_empty") and _on(s, "potion_empty_return", True):
        return Action(RETURN, "물약 없음 귀환", s.get("return_key") or "F8")

    emg = s.get("emergency_potion") or s.get("backup_potion") or {}
    emg_pct = s.get("emergency_pct", s.get("red_pct", 45))
    if hp <= _pct(s, "emergency_pct", emg_pct if isinstance(emg_pct, (int, float)) else 45):
        k = _key(emg, s.get("potion_key_alt") or "F6")
        if k:
            return Action(POTION2, "2차 물약", k)

    main = s.get("main_potion") or {}
    if hp <= _pct(s, "potion_start_pct", 80):
        k = _key(main, s.get("potion_key") or "F5")
        if k:
            return Action(POTION1, "1차 물약", k)

    if _on(s, "mp_recover_enabled", False) and mp is not None:
        if mp <= _pct(s, "mp_emergency_pct", 15):
            k = _key(s.get("mp_potion2"), "")
            if k:
                return Action(MP_POTION, "2차 MP", k)
        if mp <= _pct(s, "mp_start_pct", 30):
            k = _key(s.get("mp_potion"), "")
            if k:
                return Action(MP_POTION, "1차 MP", k)

    if state.get("poisoned") and _on(s, "antidote", True):
        return Action(ANTIDOTE, "해독", s.get("antidote_key") or "F2")

    if state.get("func_due"):
        return Action(FUNC_ITEM, "기능 아이템", extra=state.get("func_due"))

    if state.get("skill_due"):
        return Action(SKILL, "공격 마법", extra=state.get("skill_due"))

    pickup_ok = _on(s, "pickup_enabled", True)
    if pickup_ok and state.get("item_nearby"):
        if _on(s, "pickup_priority", False) or not state.get("in_combat"):
            wlim = _pct(s, "pickup_weight_pct", 70)
            if not _on(s, "pickup_weight_enabled", True) or weight is None or weight < wlim:
                return Action(PICKUP, "아이템 줍기")

    if state.get("buff_due"):
        return Action(BUFF, "버프 갱신", extra=state.get("buff_due"))

    if _on(s, "shapechange", True) and state.get("transform_due"):
        return Action(TRANSFORM, "변신", s.get("transformKey") or s.get("shapechange_key") or "F3")

    if _on(s, "auto_attack", True) and state.get("in_combat"):
        return Action(ATTACK, "전투")
    if _on(s, "auto_attack", True) and state.get("mob_nearby"):
        return Action(ATTACK, "공격")

    return Action(SEARCH, "탐색")
