"""클래스 프로필 보존 + 변신 필터 (BTS-1033575)."""
from bot_settings import switch_class
from class_config import CLASS_CONFIG
from transform_data import TRANSFORM_DATA, eligible, sort_recent


def test_클래스_전환시_이전_설정을_보존한다():
    data = {
        "characterClass": "knight",
        "buff_haste2_kind": "용기의 물약",
        "buff_haste2_key": "F7",
        "main_potion": {"key": "F5", "kind": "주홍"},
        "classProfiles": {},
    }
    data = switch_class(data, "elf")
    assert data["characterClass"] == "elf"
    assert data["classProfiles"]["knight"]["buff_haste2_key"] == "F7"
    data["buff_haste2_kind"] = "엘븐 와퍼"
    data["buff_haste2_key"] = "F9"
    data = switch_class(data, "knight")
    assert data["buff_haste2_key"] == "F7"
    assert data["buff_haste2_kind"] == "용기의 물약"


def test_마법사_버프에_2단가속이_없고_지혜_파란이_있다():
    ids = [b["id"] for b in CLASS_CONFIG["wizard"]["buffs"]]
    assert "haste2" not in ids
    assert "wisdom" in ids and "blue" in ids
    assert CLASS_CONFIG["wizard"]["showMp"] is True
    assert any(b["name"] == "용기의 물약" for b in CLASS_CONFIG["knight"]["buffs"])
    assert any(b["name"] == "악마의 피" for b in CLASS_CONFIG["prince"]["buffs"])
    assert any(b["name"] == "엘븐 와퍼" for b in CLASS_CONFIG["elf"]["buffs"])


def test_활_레벨27은_산적은_빼고_오크스카우트는_넣는다():
    ok = [t["id"] for t in TRANSFORM_DATA if eligible(t, 27, "bow")]
    assert "orc_scout" in ok
    assert "skeleton_archer" in ok
    assert "bandit" not in ok  # min 30
    spear = [t["id"] for t in TRANSFORM_DATA if eligible(t, 50, "spear")]
    assert "black_knight" in spear
    assert "orc_scout" not in spear


def test_최근_사용_정렬():
    items = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    hist = [{"id": "c", "lastUsedAt": 3}, {"id": "a", "lastUsedAt": 1}]
    assert [t["id"] for t in sort_recent(items, hist)] == ["c", "a", "b"]


def test_공격마법_카탈로그가_클래스별이다():
    from class_config import SKILLS
    assert len(SKILLS["wizard"]) >= 8
    names = [s["name"] for s in SKILLS["elf"]]
    assert "이럽션" in names and "에너지 볼트" in names
    assert "쇼크 스턴" in [s["name"] for s in SKILLS["knight"]]


def test_샤르나_스크롤_종류가_분리된다():
    kinds = {t["scrollKind"] for t in TRANSFORM_DATA}
    assert "NORMAL_SCROLL" in kinds
    assert "SHARNA_SCROLL" in kinds
