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
# 리니지 클래식 회복 물약(네이버 정리, 랜덤 범위 + hp_max 253 기준 평균%p):
# 빨간 6~27(평균16=6%) — F5 실측 +20과 일치(주 물약)
# 주홍 26~68(평균50=20%) / 맑은·엔트열매 44~107(평균75=30%) — 위기용
# 캐시템: 활기찬 물약=맑은과 회복 동일(저렴/가벼움), 물약 주머니=주홍 수령 추천
POTION_KINDS = {
    "빨간": 8,     # HP 6~27 — 주 물약(F5 실측 +20)
    "주홍": 20,    # HP 26~68
    "맑은": 30,    # HP 44~107 — 위기 물약(감별 +28%p↑ 확정)
    "엔트열매": 30, # HP 44~107(맑은 동급)
}

DEFAULTS = {
    # 물약 슬롯(사용자 지시 2026-09-15: 키 배치 + 종류별 회복량 계산).
    # heal_pct = 물약 1개 회복량(최대 HP 대신 %). 종류 프리셋은
    # POTION_KINDS 참조. 실측 학습(potion_keys EMA)이 값을 수렴시킨다.
    "main_potion": {"key": "F5", "kind": "맑은", "heal_pct": 8},
    "potion_key": "F5",        # 구 UI loadSet 필드
    "orange_key": "F5",        # 구 UI(v3 3종 그리드) 호환 — 주 물약 표시
    "red_key": "",
    "green_key": "",
    "crisis_potion": {"key": "", "kind": "", "heal_pct": 0},  # 위기용(빈=주 물약)
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
    """UI 저장 — 기본값에 병합해 기록. 검증 실패 항목은 무시."""
    data = dict(DEFAULTS)
    data.update({k: v for k, v in payload.items() if k in DEFAULTS})
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _cache["t"] = 0.0  # 캐시 무효화 — 즉시 반영
    return data
