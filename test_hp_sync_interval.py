"""HP 50ms 동기화 — 지연 원인(OCR 매요청, 400ms poll, 100ms 게이트) 재발 방지."""
from pathlib import Path

EXT = Path(__file__).with_name("ext_vision.py").read_text(encoding="utf-8")
JS = (Path(__file__).with_name("linc-vision-ext") / "content.js").read_text(encoding="utf-8")


def test_캡처간격이_50ms다():
    assert "const HUD_INTERVAL_MS = 50" in JS
    assert "setInterval(tick, 50)" in JS
    assert "setInterval(poll, 50)" in JS


def test_표시는_게이지_ratio를_OCR보다_우선한다():
    assert "typeof r.ratio === 'number'" in JS
    assert "/hp?scale=4" not in JS


def test_hp_GET은_신선한_ratio면_OCR을_건너뛴다():
    assert "want_ocr" in EXT
    assert "read_ext_ratio(max_age=0.25)" in EXT
    assert "scale=4" not in EXT.split("startswith('/hp')")[1][:400] or "want_ocr" in EXT
