"""LINC-HUD 계약 (BTS-1033572)."""
from pathlib import Path
import re

import bot_settings

CONTENT = Path(__file__).with_name("linc-vision-ext") / "content.js"
SRC = CONTENT.read_text(encoding="utf-8")


def test_표시이름이_LINC_HUD다():
    assert "LINC-HUD" in SRC
    assert "LINC BOT" not in SRC


def test_고정폭_420_금지():
    assert "width:420px" not in SRC
    assert "width: 420px" not in SRC


def test_퍼센트_회복_표시가_없다():
    assert re.search(r"\+[0-9]+%", SRC) is None
    assert "healMin" in SRC and "healMax" in SRC


def test_게임실행_버튼과_같은_부모에_붙인다():
    assert "function findLaunchButton()" in SRC
    assert "+ 게임 실행" in SRC
    assert "btn.parentElement.after" in SRC
    assert "width:100%" in SRC


def test_아코디언이_없다():
    assert "classList.toggle('open'" not in SRC
    assert "#lb-opts{display:none" not in SRC


def test_중복_id가_없다():
    ids = re.findall(r'\bid="([^"]+)"', SRC)
    dup = sorted({i for i in ids if ids.count(i) > 1})
    assert dup == [], dup


def test_물약_실측이_파이썬과_같다():
    m = re.search(r"const POTIONS = \{(.+?)\};", SRC, re.S)
    assert m
    js_min = dict(re.findall(r"'([^']+)':\s*\{[^}]*healMin:(\d+)", m.group(1)))
    js_max = dict(re.findall(r"'([^']+)':\s*\{[^}]*healMax:(\d+)", m.group(1)))
    for k, spec in bot_settings.POTIONS.items():
        assert int(js_min[k]) == spec["healMin"]
        assert int(js_max[k]) == spec["healMax"]


def test_필수_설정_필드가_저장된다():
    for key in (
        "emergency_potion", "fallback_on_empty", "potion_empty_return",
        "pickup_enabled", "weight_return", "buff_green", "shapechange",
        "antidote", "auto_attack", "aggro_first", "manner_hunt",
        "search_range", "target_timeout_sec",
    ):
        assert key in SRC
        assert key in bot_settings.DEFAULTS


def test_ATS_누락기능이_HUD에_있다():
    for key in ("1차 물약", "2차 물약", "MP 회복", "MP 귀환", "기능 아이템",
                "공격 마법", "사냥 위치 제한", "lh-skill-box", "lh-func-box"):
        assert key in SRC, key
    for key in ("mp_potion", "attack_skills", "func_items", "hunt_anchor_range",
                "mp_return_enabled", "no_combat_sec"):
        assert key in bot_settings.DEFAULTS, key


def test_클래스와_변신_데이터가_HUD에_연결된다():
    assert "st-class" in SRC
    assert "classProfiles" in SRC
    assert "function changeClass" in SRC
    assert "function renderBuffs" in SRC
    assert "function listedTransforms" in SRC
    assert "preferredTransformId" in bot_settings.DEFAULTS


def test_일반물약_기본이_주홍_F5다():
    assert bot_settings.DEFAULTS["main_potion"]["kind"] == "주홍"
    assert bot_settings.DEFAULTS["main_potion"]["key"] == "F5"
    assert bot_settings.DEFAULTS["emergency_potion"]["kind"] == "맑은"
    assert bot_settings.DEFAULTS["emergency_potion"]["key"] == "F6"
