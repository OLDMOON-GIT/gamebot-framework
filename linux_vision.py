"""로그인된 Linux 퍼플온 창의 실측 좌표로 상태를 판독한다.

빨간 이름은 플레이어일 수도 있어, 실물로 확인한 몬스터 이름만 공격 후보로
승격한다. 현재 마을 화면에서 확인하지 못한 몬스터는 임의로 등록하지 않는다.
"""
import math
import re
import subprocess

import cv2
import numpy as np


WINDOW_SIZE = (1933, 1332)
GAME_RECT = (500, 197, 1433, 1074)
PLAY_RECT = (520, 220, 1300, 750)
HP_RECT = (1000, 1045, 140, 35)
MP_RECT = (1250, 1045, 110, 35)
ZONE_RECT = (1765, 995, 165, 45)
URL_RECT = (190, 50, 500, 50)
PANEL_CLOSE_RECT = (1510, 200, 90, 40)
INVENTORY_GRID_RECT = (1580, 232, 300, 565)
# 이름표 중심에서 실제 몸체까지 실물로 측정한 (가로, 세로) 오프셋만 등록한다.
# 좌표는 WINDOW_SIZE 캘리브레이션에 종속되며 이름만 등록해서는 공격하지 않는다.
VERIFIED_TARGET_PROFILES = {}

# winbot.py(네이티브 창 실측)에서 이식한 프레임 차분 몹 탐지 파라미터.
MOTION_THRESHOLD = 35
MOB_MIN_AREA = 25
MOB_MAX_AREA = 4000
CHAR_EXCLUDE_RADIUS = 90
CHAR_BELOW_BAR = 45


def crop(img, rect):
    x, y, width, height = rect
    return img[y:y + height, x:x + width]


def ocr(img, *, whitelist=None, lang="eng", scale=2):
    """파일이나 로그인 정보에 접근하지 않고 메모리의 화면 조각만 OCR한다."""
    enlarged = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    ok, encoded = cv2.imencode(".png", enlarged)
    if not ok:
        raise RuntimeError("OCR 화면 인코딩 실패")
    command = ["tesseract", "stdin", "stdout", "--psm", "7", "-l", lang]
    if whitelist:
        command.extend(["-c", "tessedit_char_whitelist=" + whitelist])
    result = subprocess.run(command, input=encoded.tobytes(), capture_output=True,
                            timeout=4, check=True)
    return result.stdout.decode("utf-8").strip()


def parse_ratio(text, label):
    """분모/슬래시/접두어가 없거나 범위를 벗어난 OCR은 추측하지 않는다."""
    match = re.fullmatch(r"\s*" + label + r"\s*:?\s*(\d+)\s*/\s*(\d+)\s*", text)
    if not match:
        return None
    current, maximum = map(int, match.groups())
    if maximum <= 0 or current > maximum:
        return None
    return current / maximum


def zone_kind(text):
    """첫 단어(safety/normal/combat)는 정확히 일치해야 하고 뒤의 zone 변형만
    실물 오독(zoHe/cone)을 허용한다. 첫 단어가 깨지면 unknown으로 차단한다."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    if not words:
        return "unknown"
    head, tail = words[0], "".join(words[1:])
    zone_like = tail.startswith(("zone", "cone", "zo", "z0ne"))
    if head in {"safety", "satety", "safey", "satefy"} and zone_like:
        return "safe"
    if head in {"normal", "combat"} and zone_like:
        return "combat"
    return "unknown"


def zone_read(img):
    """파란 zone 텍스트를 파랑 잉크 이진화로 읽어 글자 오독을 줄인다."""
    region = crop(img, ZONE_RECT)
    channels = region.astype(np.int16)
    ink = ((channels[:, :, 0] - channels[:, :, 2] > 25)
           & (channels[:, :, 0] - channels[:, :, 1] > 10)
           & (channels[:, :, 0] > 90)).astype(np.uint8) * 255
    enlarged = cv2.resize(255 - ink, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
    return ocr(enlarged, scale=1)


def inventory_grid_visible(img):
    """실물 인벤토리의 4열·8행 격자를 감지하여 Close OCR 실패도 차단한다."""
    region = crop(img, INVENTORY_GRID_RECT)
    edges = cv2.Canny(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY), 45, 100)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100,
                            minLineLength=210, maxLineGap=8)
    horizontal, vertical = [], []
    for line in [] if lines is None else lines[:, 0]:
        x1, y1, x2, y2 = map(int, line)
        if abs(y2 - y1) <= 2 and abs(x2 - x1) >= 220:
            horizontal.append((y1 + y2) // 2)
        if abs(x2 - x1) <= 2 and abs(y2 - y1) >= 450:
            vertical.append((x1 + x2) // 2)

    def regular_lines(values, minimum):
        distinct = []
        for value in sorted(values):
            if not distinct or value - distinct[-1] > 15:
                distinct.append(value)
        spacings = np.diff(distinct)
        return len(distinct) >= minimum and np.count_nonzero(
            (spacings >= 60) & (spacings <= 85)) >= minimum - 1

    return regular_lines(horizontal, 6) and regular_lines(vertical, 4)


def panel_visible(img):
    """현재 실물로 확인한 우측 인벤토리/Close 메뉴가 열리면 전체 입력 차단."""
    if inventory_grid_visible(img):
        return True
    return bool(re.search(r"\bclose\b", ocr(crop(img, PANEL_CLOSE_RECT)), re.IGNORECASE))


def validate_target_profiles(profiles):
    """JSON 타겟 설정을 검증하고 OCR 이름과 일치하도록 공백을 정규화한다."""
    if not isinstance(profiles, dict):
        raise ValueError("타겟 프로필은 {몬스터 이름: [가로 오프셋, 세로 오프셋]} 객체여야 합니다")
    validated = {}
    for name, offset in profiles.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("타겟 이름은 비어 있지 않은 문자열이어야 합니다")
        normalized = re.sub(r"\s+", "", name)
        if normalized in validated:
            raise ValueError("공백을 제거하면 중복되는 타겟 이름입니다: " + name)
        if (not isinstance(offset, (tuple, list)) or len(offset) != 2
                or any(type(value) is not int for value in offset) or not any(offset)):
            raise ValueError("몸체 오프셋은 0,0이 아닌 정수 두 개여야 합니다: " + name)
        if abs(offset[0]) >= PLAY_RECT[2] or abs(offset[1]) >= PLAY_RECT[3]:
            raise ValueError("몸체 오프셋이 플레이 영역 크기를 벗어납니다: " + name)
        validated[normalized] = tuple(offset)
    return validated


def body_target(name, center_x, center_y, target_profiles=None):
    """검증된 몸체 좌표가 없거나 플레이 영역 밖이면 공격 대상이 아니다."""
    profiles = VERIFIED_TARGET_PROFILES if target_profiles is None else target_profiles
    offset = profiles.get(name)
    if (not isinstance(offset, (tuple, list)) or len(offset) != 2
            or any(type(value) is not int for value in offset) or not any(offset)):
        return None
    x, y = center_x + offset[0], center_y + offset[1]
    left, top, width, height = PLAY_RECT
    # 하단 10픽셀은 기존 X11 입력기가 차단하는 HUD 경계 여백이다.
    if not (left < x < left + width and top < y < top + height - 10):
        return None
    return x, y


def red_name_candidates(img):
    """HUD/사이드바/캐릭터 체력 막대를 제외한 빨강 텍스트 후보만 반환한다."""
    x0, y0, width, height = PLAY_RECT
    region = crop(img, PLAY_RECT)
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 140, 130), (8, 255, 255))
    mask |= cv2.inRange(hsv, (172, 140, 130), (180, 255, 255))
    joined = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 7), np.uint8))
    contours, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    result = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if not (18 <= w <= 200 and 9 <= h <= 30 and 1.5 < w / h < 14):
            continue
        ink = mask[y:y + h, x:x + w]
        density = np.count_nonzero(ink) / (w * h)
        # 꽉 찬 빨강 막대, 넓은 옷/오브젝트를 텍스트로 간주하지 않는다.
        components = cv2.connectedComponents(ink)[0] - 1
        if not (0.08 <= density <= 0.65 and components >= 3):
            continue
        center_x, center_y = x0 + x + w // 2, y0 + y + h // 2
        result.append((center_x, center_y, int(cv2.contourArea(contour)),
                       (x0 + x, y0 + y, w, h)))
    return result


def find_character(img):
    """머리 위 HP 막대(빨강 채움+청백 트랙)로 캐릭터 위치를 찾는다.

    winbot.py 실측 알고리즘 이식: HSV red|blue 마스크 + 가로 close →
    25~130px 가로형 컨투어, 아래 15~95px 밝기 ≥22 조건으로 오탐 제거.
    반환: (cx, cy, hp_ratio) 또는 None.
    """
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, (0, 150, 120), (10, 255, 255)) | \
        cv2.inRange(hsv, (170, 150, 120), (180, 255, 255))
    blue = cv2.inRange(hsv, (95, 120, 100), (130, 255, 255))
    mask = red | blue
    mask[:int(h * 0.12), :] = 0
    mask[int(h * 0.92):, :] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 25), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if not (25 <= bw <= 130 and 3 <= bh <= 18):
            continue
        # 게임 스트리밍 영역(GAME_RECT) 밖 HP바는 사이드바/HUD 오탐이다.
        gx, gy, gw, gh = GAME_RECT
        if not (gx <= x and x + bw <= gx + gw and gy <= y and y + bh <= gy + gh):
            continue
        below = img[y + bh + 15:y + bh + 95, max(0, x - 25):x + bw + 25]
        below_mean = below.mean() if below.size else 0
        if below_mean < 22:
            continue
        bar = img[y:y + bh, x:x + bw].astype(np.int16)
        rr, bb = bar[:, :, 2], bar[:, :, 0]
        red_cols = ((rr > bb + 10) & (rr > 18)).any(axis=0)
        hp = float(red_cols.sum()) / bw
        cx, cy = x + bw // 2, y + bh + CHAR_BELOW_BAR
        score = below_mean + bw * 0.5
        if best is None or score > best[0]:
            best = (score, cx, cy, hp)
    if best is None:
        return None
    return best[1], best[2], best[3]


def motion_blobs(img, prev, char_pos=None):
    """프레임 차분으로 움직이는 블롭(몹 후보)을 찾는다. 캐릭터 주변은 제외.

    반환: (블롭 리스트 [(cx, cy, 면적)], 화면 변경 비율). 카메라 스크롤 중
    (변경 비율 과다)에는 빈 리스트를 돌려 오판을 막는다.
    """
    left, top, width, height = PLAY_RECT
    a = img[top:top + height, left:left + width]
    b = prev[top:top + height, left:left + width]
    diff = cv2.absdiff(a, b)
    gray = diff.max(axis=2).astype(np.uint8)
    _, thresholded = cv2.threshold(gray, MOTION_THRESHOLD, 255, cv2.THRESH_BINARY)
    thresholded = cv2.morphologyEx(thresholded, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    thresholded = cv2.dilate(thresholded, np.ones((5, 5), np.uint8))
    change_ratio = float((thresholded > 0).mean())
    if change_ratio > 0.25:
        return [], change_ratio
    contours, _ = cv2.findContours(thresholded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    blobs = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if not (MOB_MIN_AREA <= area <= MOB_MAX_AREA):
            continue
        moments = cv2.moments(contour)
        if not moments["m00"]:
            continue
        bx = left + int(moments["m10"] / moments["m00"])
        by = top + int(moments["m01"] / moments["m00"])
        if char_pos and math.hypot(bx - char_pos[0], by - char_pos[1]) <= CHAR_EXCLUDE_RADIUS:
            continue
        blobs.append((bx, by, int(area)))
    return blobs, change_ratio


def analyze(img, target_profiles=None):
    profiles = validate_target_profiles(
        VERIFIED_TARGET_PROFILES if target_profiles is None else target_profiles)
    result = {"hp": None, "mp": None, "ready": False, "game_visible": False,
              "safe_zone": False, "mobs": [], "candidates": [],
              "reason": "화면 크기 불일치"}
    if img is None or img.ndim != 3 or img.shape[2] != 3:
        return result
    if (img.shape[1], img.shape[0]) != WINDOW_SIZE:
        return result
    try:
        url = ocr(crop(img, URL_RECT))
        if "purpleon.plaync.com/webplay/linclassic" not in url.replace(" ", ""):
            result["reason"] = "퍼플온 리니지 URL 확인 실패"
            return result
        result["hp"] = parse_ratio(ocr(crop(img, HP_RECT),
                                          whitelist="HMP:0123456789/"), "HP")
        result["mp"] = parse_ratio(ocr(crop(img, MP_RECT),
                                          whitelist="HMP:0123456789/"), "MP")
        # 이동 전용 입력은 zone 판독과 무관하게 게임 화면 확인만으로 허용한다.
        result["game_visible"] = result["hp"] is not None and result["hp"] > 0
        zone = zone_kind(zone_read(img))
        result["safe_zone"] = zone == "safe"
        if result["hp"] is None:
            result["reason"] = "HP 판독 실패: 입력 차단"
            return result
        if result["hp"] == 0:
            result["reason"] = "캐릭터 사망: 입력 차단"
            return result
        if zone == "unknown":
            result["reason"] = "지역 상태 판독 실패: 입력 차단"
            return result
        if panel_visible(img):
            result["reason"] = "인벤토리 또는 메뉴 패널 열림: 입력 차단"
            return result
        result["ready"] = True
        if result["safe_zone"]:
            result["reason"] = "마을 안전 구역: 사냥 입력 차단"
            return result
        candidates = red_name_candidates(img)
        result["candidates"] = [entry[:3] for entry in candidates]
        for x, y, area, rect in candidates:
            if not profiles:
                break
            name = re.sub(r"\s+", "", ocr(crop(img, rect), lang="kor+eng"))
            target = body_target(name, x, y, profiles)
            if target is not None:
                result["mobs"].append((*target, area))
        result["reason"] = ("검증된 몬스터 이름 탐지" if result["mobs"] else
                            "검증된 몬스터 몸체 프로필 없음: 공격 대기")
    except (OSError, subprocess.SubprocessError, cv2.error) as exc:
        result.update(ready=False, mobs=[], reason="화면 판독 오류: " + str(exc))
    return result
