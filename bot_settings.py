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
DEFAULTS = {
    "red_key": "",             # 빨간 물약(대회복) 키 — 위기 구간용
    "orange_key": "F6",        # 주홍 물약(보통) — 기본 물약(사용자 실측 F6)
    "green_key": "",           # 초록 물약(소회복) — 가벼운 구간용
    "potion_key_alt": "F5",    # 보조(무반응 폴백)
    "return_key": "F8",        # 귀환 주문서
    "potion_start_pct": 80,    # 이 % 밑이면 물약 시작
    "recover_to_pct": 80,      # 이 % 이상까지 채운다(연속 투입 목표)
    "red_pct": 45,             # 이 % 밑이면 빨간 물약(red_key 지정 시)
    "green_pct": 0,            # 이 % 이상이면 초록 물약(green_key 지정 시)
    "danger_pct": 20,          # 이 % 밑이면 F8 귀환
    "chain_max": 6,            # 한 턴 연속 투입 상한(위기시 +2)
    "enabled": True,           # 봇 물약 on/off
}

_cache = {"t": 0.0, "data": dict(DEFAULTS)}


def load(refresh=5.0):
    """설정 로드(캐시). 파일이 없으면 기본값."""
    now = time.monotonic()
    if now - _cache["t"] < refresh:
        return _cache["data"]
    _cache["t"] = now
    data = dict(DEFAULTS)
    try:
        with open(PATH) as f:
            data.update({k: v for k, v in json.load(f).items()
                         if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    _cache["data"] = data
    return data


def save(payload):
    """UI 저장 — 기본값에 병합해 기록. 검증 실패 항목은 무시."""
    data = dict(DEFAULTS)
    data.update({k: v for k, v in payload.items() if k in DEFAULTS})
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _cache["t"] = 0.0  # 캐시 무효화 — 즉시 반영
    return data
