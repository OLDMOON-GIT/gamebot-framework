from attack_skills import next_skill, ready

SK = [
    {"id": "none", "name": "-", "enabled": False},
    {"id": "energy_bolt", "name": "에너지 볼트", "enabled": True, "key": "F1",
     "mpMin": 10, "hpMin": 0, "intervalSec": 3, "maxCount": 0},
    {"id": "eruption", "name": "이럽션", "enabled": True, "key": "F2",
     "mpMin": 40, "hpMin": 50, "intervalSec": 3, "maxCount": 0},
]


def test_비활성_none은_건너뛴다():
    assert next_skill(SK, 0.9, 0.9, 10, {}, {}).get("id") == "energy_bolt"


def test_MP부족이면_다음스킬():
    sk = next_skill(SK, 0.9, 0.05, 10, {}, {})
    assert sk is None  # bolt도 mpMin 10


def test_이럽션은_HP와_MP조건():
    sk = next_skill(SK, 0.9, 0.5, 10, {}, {})
    assert sk["id"] == "energy_bolt"
    sk = next_skill(SK, 0.9, 0.5, 10, {"energy_bolt": 9.0}, {})
    assert sk["id"] == "eruption"


def test_간격미달이면_스킵():
    assert ready(SK[1], 0.9, 0.9, 11, last_used=9.5, used_count=0) is False
    assert ready(SK[1], 0.9, 0.9, 13, last_used=9.5, used_count=0) is True


def test_횟수제한():
    sk = {**SK[1], "maxCount": 2}
    assert ready(sk, 0.9, 0.9, 10, None, 2) is False
    assert ready(sk, 0.9, 0.9, 10, None, 1) is True
