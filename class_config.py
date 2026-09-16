"""클래스별 버프/표시 설정. UI if문 하드코딩 금지 — 여기만 고친다."""

CLASSES = [
    {"id": "prince", "name": "군주"},
    {"id": "knight", "name": "기사"},
    {"id": "elf", "name": "요정"},
    {"id": "wizard", "name": "마법사"},
]

WEAPONS = [
    {"id": "sword1h", "name": "한손검"},
    {"id": "sword2h", "name": "양손검"},
    {"id": "bow", "name": "활"},
    {"id": "spear", "name": "창"},
    {"id": "staff", "name": "지팡이"},
    {"id": "dagger", "name": "단검"},
    {"id": "other", "name": "기타"},
]

# 1단 가속은 전 클래스 공통.
HASTE1 = {
    "id": "haste1",
    "name": "초록 물약",
    "label": "1단 가속",
    "durationMin": 5,
    "boostMin": 30,
    "variants": [
        {"id": "green", "name": "초록 물약", "durationMin": 5},
        {"id": "green_strong", "name": "강화 초록 물약", "durationMin": 30},
    ],
}

CLASS_CONFIG = {
    "knight": {
        "name": "기사",
        "showMp": False,
        "buffs": [
            dict(HASTE1),
            {"id": "haste2", "name": "용기의 물약", "label": "2단 가속",
             "durationMin": 5, "note": "지속 약 5분"},
        ],
    },
    "prince": {
        "name": "군주",
        "showMp": False,
        "buffs": [
            dict(HASTE1),
            {"id": "haste2", "name": "악마의 피", "label": "2단 가속",
             "durationMin": 10, "note": "지속 약 10분"},
        ],
    },
    "elf": {
        "name": "요정",
        "showMp": False,
        "buffs": [
            dict(HASTE1),
            {"id": "haste2", "name": "엘븐 와퍼", "label": "2단 가속",
             "durationMin": 8, "note": "지속 약 8분"},
        ],
    },
    "wizard": {
        "name": "마법사",
        "showMp": True,
        "buffs": [
            dict(HASTE1),
            {"id": "wisdom", "name": "지혜의 물약", "label": "지혜의 물약",
             "durationMin": 5, "note": "SP +2 · 지속 약 5분"},
            {"id": "blue", "name": "파란 물약", "label": "파란 물약",
             "durationMin": 10, "note": "MP 회복량 증가 · 지속 약 10분"},
        ],
    },
}

MP_POTIONS = [
    {"id": "", "name": "-"},
    {"id": "mana", "name": "마력 회복제"},
    {"id": "mana_hi", "name": "고급 마력 회복제"},
    {"id": "mana_strong", "name": "강력 마력 회복제"},
]

FUNC_ITEM_CATALOG = [
    {"id": "green", "name": "초록 물약", "triggerType": "TIMER", "duration": 300},
    {"id": "green_strong", "name": "강화 초록 물약", "triggerType": "TIMER", "duration": 1800},
    {"id": "brave", "name": "용기의 물약", "triggerType": "TIMER", "duration": 300},
    {"id": "devil", "name": "악마의 피", "triggerType": "TIMER", "duration": 600},
    {"id": "elven", "name": "엘븐 와퍼", "triggerType": "TIMER", "duration": 480},
    {"id": "wisdom", "name": "지혜의 물약", "triggerType": "TIMER", "duration": 300},
    {"id": "blue", "name": "파란 물약", "triggerType": "TIMER", "duration": 600},
    {"id": "antidote", "name": "해독제", "triggerType": "STATUS", "duration": 0},
    {"id": "bless_armor", "name": "블레스드 아머", "triggerType": "TIMER", "duration": 1200},
    {"id": "enchant_weapon", "name": "전투 강화 주문서", "triggerType": "MANUAL_CONDITION", "duration": 0},
]

SKILLS = {
    "knight": [
        {"id": "none", "name": "-"},
        {"id": "shock_stun", "name": "쇼크 스턴"},
        {"id": "reduction_armor", "name": "리덕션 아머"},
        {"id": "solid_carriage", "name": "솔리드 캐리지"},
        {"id": "bounce_attack", "name": "바운스 어택"},
    ],
    "prince": [
        {"id": "none", "name": "-"},
        {"id": "true_target", "name": "트루 타겟"},
        {"id": "glowing_aura", "name": "글로잉 오라"},
        {"id": "shining_shield", "name": "샤이닝 실드"},
        {"id": "brave_mental", "name": "브레이브 멘탈"},
        {"id": "call_lightning", "name": "콜 라이트닝"},
    ],
    "elf": [
        {"id": "none", "name": "-"},
        {"id": "energy_bolt", "name": "에너지 볼트"},
        {"id": "triple_arrow", "name": "트리플 애로우"},
        {"id": "eruption", "name": "이럽션"},
        {"id": "sunburst", "name": "선버스트"},
        {"id": "call_lightning", "name": "콜 라이트닝"},
        {"id": "blizzard", "name": "블리자드"},
        {"id": "blood_to_soul", "name": "블러드 투 소울"},
    ],
    "wizard": [
        {"id": "none", "name": "-"},
        {"id": "energy_bolt", "name": "에너지 볼트"},
        {"id": "ice_dagger", "name": "아이스 대거"},
        {"id": "wind_cutter", "name": "윈드 커터"},
        {"id": "eruption", "name": "이럽션"},
        {"id": "call_lightning", "name": "콜 라이트닝"},
        {"id": "cone_of_cold", "name": "콘 오브 콜드"},
        {"id": "sunburst", "name": "선버스트"},
        {"id": "blizzard", "name": "블리자드"},
        {"id": "tornado", "name": "토네이도"},
    ],
}

EMPTY_SKILL = {
    "id": "none", "name": "-", "enabled": False, "key": "",
    "mpMin": 0, "hpMin": 0, "targetHpMax": 100,
    "intervalSec": 3, "maxCount": 0,
}
