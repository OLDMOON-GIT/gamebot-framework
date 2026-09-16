"""공격 마법 8칸 순서 + 조건 (BTS-1033580). 키 입력은 호출부가 한다."""


def ready(skill, hp, mp, now, last_used, used_count):
    if not skill or skill.get("id") in (None, "", "none"):
        return False
    if not skill.get("enabled"):
        return False
    if hp is not None and hp < float(skill.get("hpMin") or 0) / 100.0:
        return False
    if mp is not None and mp < float(skill.get("mpMin") or 0) / 100.0:
        return False
    tmax = skill.get("targetHpMax")
    thp = skill.get("target_hp")
    if tmax is not None and thp is not None and thp > float(tmax) / 100.0:
        return False
    interval = float(skill.get("intervalSec") or 0)
    if interval and last_used is not None and (now - last_used) < interval:
        return False
    maxc = int(skill.get("maxCount") or 0)
    if maxc > 0 and int(used_count or 0) >= maxc:
        return False
    return True


def next_skill(skills, hp, mp, now, last_map, count_map):
    """순서대로 첫 사용 가능 스킬. 없으면 None."""
    for sk in skills or []:
        sid = sk.get("id")
        if ready(sk, hp, mp, now, (last_map or {}).get(sid), (count_map or {}).get(sid, 0)):
            return sk
    return None
