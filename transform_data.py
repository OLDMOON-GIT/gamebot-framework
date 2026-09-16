"""리니지 클래식 변신 카탈로그. HUD는 이 목록만 표시한다. 업데이트 시 여기만 추가."""

# weaponTypes: sword1h/sword2h/bow/spear/staff/dagger/any
# attackType: melee/ranged/magic/any
# scrollKind: NORMAL_SCROLL / SHARNA_SCROLL
TRANSFORM_DATA = [
    {"id": "orc_scout", "name": "오크 스카우트", "minLevel": 1,
     "weaponTypes": ["bow", "dagger"], "attackType": "ranged",
     "scrollKind": "NORMAL_SCROLL"},
    {"id": "skeleton_archer", "name": "해골 궁수", "minLevel": 1,
     "weaponTypes": ["bow"], "attackType": "ranged",
     "scrollKind": "NORMAL_SCROLL"},
    {"id": "bandit", "name": "산적", "minLevel": 30,
     "weaponTypes": ["bow"], "attackType": "ranged",
     "scrollKind": "NORMAL_SCROLL"},
    {"id": "darkelf_ranger", "name": "다크엘프 레인저", "minLevel": 40,
     "weaponTypes": ["bow"], "attackType": "ranged",
     "scrollKind": "NORMAL_SCROLL"},
    {"id": "werewolf", "name": "늑대인간", "minLevel": 1,
     "weaponTypes": ["sword1h", "dagger"], "attackType": "melee",
     "scrollKind": "NORMAL_SCROLL"},
    {"id": "skeleton", "name": "스켈레톤", "minLevel": 1,
     "weaponTypes": ["sword1h"], "attackType": "melee",
     "scrollKind": "NORMAL_SCROLL"},
    {"id": "orc_warrior", "name": "오크 전사", "minLevel": 1,
     "weaponTypes": ["sword1h", "sword2h"], "attackType": "melee",
     "scrollKind": "NORMAL_SCROLL"},
    {"id": "bugbear", "name": "버그베어", "minLevel": 10,
     "weaponTypes": ["sword2h"], "attackType": "melee",
     "scrollKind": "NORMAL_SCROLL"},
    {"id": "ghoul", "name": "구울", "minLevel": 15,
     "weaponTypes": ["dagger"], "attackType": "melee",
     "scrollKind": "NORMAL_SCROLL"},
    {"id": "troll", "name": "트롤", "minLevel": 20,
     "weaponTypes": ["sword2h"], "attackType": "melee",
     "scrollKind": "NORMAL_SCROLL"},
    {"id": "assassin", "name": "어쌔신", "minLevel": 30,
     "weaponTypes": ["dagger"], "attackType": "melee",
     "scrollKind": "NORMAL_SCROLL"},
    {"id": "zombie_elmore", "name": "좀비 엘모어 병사", "minLevel": 45,
     "weaponTypes": ["spear"], "attackType": "melee",
     "scrollKind": "NORMAL_SCROLL"},
    {"id": "black_knight", "name": "흑기사", "minLevel": 50,
     "weaponTypes": ["spear"], "attackType": "melee",
     "scrollKind": "NORMAL_SCROLL"},
    {"id": "dark_lancer", "name": "다크 랜서", "minLevel": 55,
     "weaponTypes": ["spear"], "attackType": "melee",
     "scrollKind": "NORMAL_SCROLL"},
    {"id": "death_knight", "name": "데스나이트", "minLevel": 45,
     "weaponTypes": ["sword2h"], "attackType": "melee",
     "scrollKind": "NORMAL_SCROLL"},
    {"id": "elder", "name": "장로", "minLevel": 20,
     "weaponTypes": ["staff"], "attackType": "magic",
     "scrollKind": "NORMAL_SCROLL"},
    {"id": "lich", "name": "리치", "minLevel": 40,
     "weaponTypes": ["staff"], "attackType": "magic",
     "scrollKind": "NORMAL_SCROLL"},
    {"id": "dark_elf", "name": "다크엘프", "minLevel": 20,
     "weaponTypes": ["dagger", "bow"], "attackType": "any",
     "scrollKind": "NORMAL_SCROLL"},
    {"id": "sharna_wolf", "name": "샤르나 늑대", "minLevel": 1,
     "weaponTypes": ["any"], "attackType": "any",
     "scrollKind": "SHARNA_SCROLL"},
]


def eligible(item, level, weapon, cls=None):
    if int(item.get("minLevel") or 1) > int(level or 1):
        return False
    wts = item.get("weaponTypes") or ["any"]
    if "any" not in wts and weapon and weapon not in wts:
        return False
    cls_ok = item.get("classes") or ["any"]
    if "any" not in cls_ok and cls and cls not in cls_ok:
        return False
    return True


def sort_recent(items, history):
    hist = {h.get("id"): (h.get("lastUsedAt") or 0) for h in (history or [])}
    return sorted(items, key=lambda t: hist.get(t["id"], 0), reverse=True)
