"""사냥 맵 필터 — 사막 던전 4층만, 버땅/축복의땅은 안 잡는다.

실측(2026-09-17 CDP 1933x1332): 맵 이름은 하단 HUD 왼쪽
'사막 던전 4층'(노란 글씨). OCR은 앞글자 누락으로 '막 던전 4층'을
읽는다. 버땅=버림받은 자들의 땅, 축복의땅=타락한 축복의 땅.
"""
import re
import time

from linux_vision import crop, ocr, zone_kind, zone_read

# 실측 2026-09-17: (400,900,400,80) → '막 던전 4층'
MAP_RECTS = (
    (400, 900, 400, 80),
    (360, 895, 420, 70),
    (380, 900, 380, 60),
)

SKIP_KEYS = (
    "버림받은", "버림 받은", "버땅", "버린받은", "자들의땅", "자들의 땅",
    "축복의땅", "축복의 땅", "타락한축복", "타락한 축복", "축복땅",
)
ALLOW_KEYS = (
    "사막던전", "사막 던전", "막던전", "막 던전",
    "던전4층", "던전 4층", "사던",
)
FORBIDDEN_MOB = ("버그베", "bugbear")


def _norm(text):
    return re.sub(r"\s+", "", str(text or "")).lower()


def classify_map(text):
    """맵 이름 → allow / skip / unknown. 스킵 키를 먼저 본다."""
    raw = str(text or "")
    n = _norm(raw)
    if not n:
        return "unknown"
    for key in SKIP_KEYS:
        if _norm(key) in n or key in raw:
            return "skip"
    for key in ALLOW_KEYS:
        if _norm(key) in n or key in raw:
            return "allow"
    return "unknown"


def is_forbidden_mob(name):
    """버그베어는 사던 버그가 아니다. '버그' 부분매칭 금지."""
    n = _norm(name)
    return any(k in n for k in FORBIDDEN_MOB)


def read_map_name(img):
    """하단 HUD 맵 이름 OCR. 분류 가능한 텍스트가 나오면 즉시 반환."""
    last = ""
    shape = getattr(img, "shape", None)
    if not isinstance(shape, tuple) or len(shape) < 2:
        return ""
    try:
        height, width = int(shape[0]), int(shape[1])
    except (TypeError, ValueError):
        return ""
    if height < 980 or width < 800:
        return ""
    for rect in MAP_RECTS:
        try:
            text = (ocr(crop(img, rect), lang="kor") or "").strip()
        except Exception:
            text = ""
        if text:
            last = text
        if classify_map(text) != "unknown":
            return text
        try:
            text2 = (ocr(crop(img, rect), lang="kor+eng") or "").strip()
        except Exception:
            text2 = ""
        if text2:
            last = text2
        if classify_map(text2) != "unknown":
            return text2
    return last


class HuntZone:
    """맵 판독 캐시. OCR은 3초에 한 번. 전투 중 매 틱 호출해도 부담 없음.

    현재 캐릭터가 사던4층에 있으므로 초기값은 allow.
    skip이 한 번 읽히면 다음 확정 판독까지 사냥을 멈춘다.
    """

    def __init__(self, default="allow"):
        self.last = default
        self.last_name = ""
        self._at = 0.0

    def decide(self, img, force=False):
        now = time.monotonic()
        if not force and self._at and now - self._at < 3.0:
            return self.last, self.last_name
        name = read_map_name(img)
        kind = classify_map(name)
        if kind == "unknown":
            try:
                zone = zone_kind(zone_read(img))
            except Exception:
                zone = "unknown"
            if zone == "safe":
                kind = "skip"
                name = name or "Safety Zone"
        if kind != "unknown":
            self.last = kind
            if name:
                self.last_name = name
        elif name:
            self.last_name = name
        self._at = now
        return self.last, self.last_name or name
