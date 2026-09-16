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
# 물약 종류 프리셋(리니지 클래식 — 사용자 정정 2026-09-16: 초록은 속도
# 물약이라 HP 회복 0. HP 회복은 맑은/주홍/빨간 계열. %는 hp_max 253 기준)
# 리니지 클래식 회복 물약 — 등급 순서: 맑은 > 주홍 > 빨강 (사용자 정정
# 2026-09-16 + 재조사 확인: 실측 10회 평균 빨강 15 / 주홍 51.3 /
# 맑은 44~107(고급). 랜덤 범위이며 hp_max 253 기준 평균%p.
# 등급: 빨간 < 주홍 < 맑은 (사용자 지시 — 몇 번을 말해야 하는지 죄송)
POTION_KINDS = {
    "빨간": 6,     # HP 6~27, 실측 평균 15 ≈ 6%p (hp_max 253)
    "주홍": 20,    # HP 26~68 (중간)
    "맑은": 30,    # HP 44~107 (강함)
}

DEFAULTS = {
    # 물약 슬롯(사용자 지시 2026-09-15: 키 배치 + 종류별 회복량 계산).
    # heal_pct = 물약 1개 회복량(최대 HP 대신 %). 종류 프리셋은
    # POTION_KINDS 참조. 실측 학습(potion_keys EMA)이 값을 수렴시킨다.
    "main_potion": {"key": "F5", "kind": "맑은", "heal_pct": 30},
    "potion_key": "F5",        # 구 UI loadSet 필드
    "orange_key": "F5",        # 구 UI(v3 3종 그리드) 호환 — 주 물약 표시
    "red_key": "",
    "green_key": "",
    "backup_potion": {"key": "F6", "kind": "빨간", "heal_pct": 19}, # 보조 물약 기본 F6, 실측 평균 +19%p
    "potion_key_alt": "F6",    # 보조(무반응 폴백)
    "return_key": "F8",        # 귀환 주문서
    "potion_start_pct": 80,    # 이 % 밑이면 물약 시작
    "recover_to_pct": 80,      # 이 % 이상까지 채운다(연속 투입 목표)
    "red_pct": 30,             # 이 % 밑이면 위기 물약(맑은) — 45→30 하향(남발 사고)
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
