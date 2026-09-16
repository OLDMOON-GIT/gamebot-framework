"""기능 아이템 타이머/상태 트리거 (BTS-1033580)."""


def ready(item, now, last_used, flags):
    if not item or not item.get("enabled", True):
        return False
    trig = (item.get("triggerType") or "TIMER").upper()
    flags = flags or {}
    if trig == "STATUS":
        need = item.get("status") or "poisoned"
        return bool(flags.get(need))
    if trig == "HP":
        hp = flags.get("hp")
        return hp is not None and hp <= float(item.get("hpMax") or 1)
    if trig == "MP":
        mp = flags.get("mp")
        return mp is not None and mp <= float(item.get("mpMax") or 1)
    if trig == "MANUAL_CONDITION":
        return bool(flags.get("manual_" + (item.get("itemId") or "")))
    # TIMER
    dur = float(item.get("duration") or 0)
    refresh = float(item.get("refreshBefore") or 0)
    if last_used is None:
        return True
    if dur <= 0:
        return False
    remain = dur - (now - last_used)
    return remain <= refresh


def next_item(items, now, last_map, flags):
    for it in items or []:
        lid = it.get("itemId") or it.get("name")
        if ready(it, now, (last_map or {}).get(lid), flags) and it.get("hotkey"):
            return it
    return None
