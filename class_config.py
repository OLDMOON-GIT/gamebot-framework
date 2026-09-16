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
