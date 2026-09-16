"""봇 설정 — 크롬 익스텐션 UI에서 세팅하고 봇이 즉시 반영한다.

사용자 지시(2026-09-15): 게임 옵션처럼 '물약은 몇 번(키), 몇 퍼에서
얼마를 먹어라' 등을 확장 UI에서 지정. ext_vision /bot-settings 가
이 파일을 쓰고 PotionKeys 가 캐시된 채로 읽는다(5초).
"""
import json
import os
import time

PATH = "/tmp/linc-bot-linux/settings.json"

# 기본값 = 사용자가 2026-09-15에 직접 지시한 값들:
# "80퍼밑으로 가면 빨아라" / "80이상으로 채워라" / "40퍼 쭉쭉 내려가면
# 그 이상으로" / "물약이 아예없거나 20퍼미만의 경우 f8(귀환주문서)" /
# f6이 물약. 이 값들이 확장 UI 폼의 초기 표시값이기도 하다.
# 리니지 클래식 HP 물약 실측 범위(퍼센트 회복 아님).
# 빨간=체력 회복제 6~27, 주홍=고급 체력 회복제 26~68, 맑은=강력 체력 회복제 44~107.
POTIONS = {
    "빨간": {
        "name": "빨간 물약", "officialName": "체력 회복제",
        "healMin": 6, "healMax": 27, "healAverage": 16.5,
    },
    "주홍": {
        "name": "주홍 물약", "officialName": "고급 체력 회복제",
        "healMin": 26, "healMax": 68, "healAverage": 47,
    },
    "맑은": {
        "name": "맑은 물약", "officialName": "강력 체력 회복제",
        "healMin": 44, "healMax": 107, "healAverage": 75.5,
    },
}
# 구 코드 호환(heal_pct 필드). UI에는 쓰지 않는다.
POTION_KINDS = {k: v["healAverage"] for k, v in POTIONS.items()}

DEFAULTS = {
    # 일반 물약 = 주홍/F5, 위급 = 맑은/F6 (LINC-HUD 스펙).
    "main_potion": {"key": "F5", "kind": "주홍"},
    "potion_key": "F5",
    "orange_key": "F5",
    "red_key": "",
    "green_key": "",
    "emergency_potion": {"key": "F6", "kind": "맑은"},
    "backup_potion": {"key": "F6", "kind": "맑은"},
    "fallback_potion": {"key": "F4", "kind": "빨간"},
    "potion_key_alt": "F6",
    "return_key": "F8",
    "potion_start_pct": 80,
    "emergency_pct": 45,
    "recover_to_pct": 80,
    "red_pct": 45,
    "green_pct": 0,
    "danger_pct": 20,
    "chain_max": 6,
    "enabled": True,
    "return_enabled": True,
    "potion_empty_return": True,
    "fallback_on_empty": True,
    "weight_return": True,
    "weight_return_pct": 80,
    "no_combat_return": False,
    "no_combat_minutes": 10,
    "pickup_enabled": True,
    "pickup_priority": False,
    "adena_only": False,
    "pickup_weight_pct": 70,
    "buff_green": True,
    "buff_green_kind": "초록 물약",
    "buff_green_key": "",
    "buff_haste2": True,
    "buff_haste2_kind": "악마의 피",
    "buff_haste2_key": "F9",
    "shapechange": True,
    "shapechange_key": "F3",
    "shapechange_form": "오크 스카우트",
    "antidote": True,
    "antidote_key": "F2",
    "auto_attack": True,
    "aggro_first": True,
    "manner_hunt": True,
    "search_range": 10,
    "no_target_sec": 10,
    "target_timeout_sec": 60,
}

_cache = {"t": 0.0, "data": dict(DEFAULTS)}


def _with_catalog(data):
    out = dict(data)
    out["potions"] = POTIONS
    return out


def load(refresh=5.0):
    """설정 로드(캐시). 파일이 없으면 기본값."""
    now = time.monotonic()
    if now - _cache["t"] < refresh:
        return _with_catalog(_cache["data"])
    _cache["t"] = now
    data = dict(DEFAULTS)
    try:
        with open(PATH) as f:
            data.update({k: v for k, v in json.load(f).items()
                         if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    _cache["data"] = data
    return _with_catalog(data)


def save(payload):
    """UI 저장 — 기존 파일 + 기본값 + payload 병합(기존 유지)."""
    data = dict(DEFAULTS)
    try:
        with open(PATH) as f:
            data.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    data.update({k: v for k, v in payload.items() if k in DEFAULTS})
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _cache["t"] = 0.0  # 캐시 무효화 — 즉시 반영
    return data
