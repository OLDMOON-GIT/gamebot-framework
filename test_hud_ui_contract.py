"""content.js HUD 계약 — GLM이 CSS 루프에서 반복 파손한 항목을 고정한다 (BTS-1033569)."""
from pathlib import Path
import re

import bot_settings

CONTENT = Path(__file__).with_name("linc-vision-ext") / "content.js"
SRC = CONTENT.read_text(encoding="utf-8")


def test_hud_함수_있고_중복_id가_없다():
    assert "function installHudUi()" in SRC
    ids = re.findall(r'\bid="([^"]+)"', SRC)
    hud_ids = [i for i in ids if i.startswith("lb-") or i.startswith("st-") or i.startswith("v-heal")]
    dup = sorted({i for i in hud_ids if hud_ids.count(i) > 1})
    assert dup == [], f"HUD 템플릿 중복 id: {dup}"


def test_구버전_죽은_참조가_없다():
    for dead in ("st-chminus", "st-chplus", "v-chain", "lb-keyr", "lb-keyg", 'id="lb-key2"'):
        assert dead not in SRC, f"죽은 참조 잔존: {dead}"


def test_키그리드_id가_역할별로_분리된다():
    for i in ("lb-key-main", "lb-key-alt", "lb-key-return"):
        assert i in SRC, i
    assert "lb-key-crisis" not in SRC


def test_물약_종류가_파이썬_프리셋과_같다():
    m = re.search(r"const KINDS = \{([^}]+)\}", SRC)
    assert m, "KINDS 없음"
    js = {}
    for k, v in re.findall(r"'([^']+)':\s*(\d+)", m.group(1)):
        js[k] = int(v)
    assert js == bot_settings.POTION_KINDS, (js, bot_settings.POTION_KINDS)


def test_기본_위치가_게임창_왼쪽_하단이다():
    assert "bottom:0" in SRC or "bottom: 0" in SRC
    assert "max-height:82vh" in SRC or "max-height: 82vh" in SRC
    assert "function gamePaneLeft()" in SRC
    assert "document.querySelector('aside')" in SRC


def test_맑은_기본_heal_pct_가_최강값이다():
    assert bot_settings.DEFAULTS["main_potion"]["kind"] == "맑은"
    assert bot_settings.DEFAULTS["main_potion"]["heal_pct"] == bot_settings.POTION_KINDS["맑은"]
    assert bot_settings.POTION_KINDS["맑은"] > bot_settings.POTION_KINDS["주홍"] > bot_settings.POTION_KINDS["빨간"]
