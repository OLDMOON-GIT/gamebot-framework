"""로그인된 Linux 퍼플온 창의 실측 좌표로 상태를 판독한다.

빨간 이름은 플레이어일 수도 있어, 실물로 확인한 몬스터 이름만 공격 후보로
승격한다. 현재 마을 화면에서 확인하지 못한 몬스터는 임의로 등록하지 않는다.
"""
import math
import re
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np


WINDOW_SIZE = (1933, 1332)
GAME_RECT = (500, 197, 1433, 1074)
PLAY_RECT = (520, 220, 1300, 750)
HP_RECT = (870, 1002, 230, 36)  # CDP 창 실측(2026-09-07): HP 97/134 위치
MP_RECT = (1180, 1002, 140, 36)
# CDP 창에서 tesseract가 슬래시를 못 읽는다(실측). 현재/최대 숫자를
# 분리 크롭으로 읽어 비율을 구한다.
# HUD HP 숫자 크롭. 종전 (955,1005,50,32)/(1010,1005,60,32)는 실제 텍스트
# 위치와 어긋나 OCR이 빈 문자열 → 교차검증 폴백이 죽어 있었고, 그 탓에
# 게이지 트랙 stale 오판독을 아무도 못 걸러냈다(BTS-1033250).
# 2026-09-10 라이브 재실측값. capture() 프레임(1933x1332) 기준.
# 재접속마다 HUD가 수직 시프트한다(2026-09-13 실측: 게이지 y1040→1029,
# 텍스트도 동일 -11px) → ZONE_RECTS처럼 후보를 순서대로 시도한다.
HP_CUR_RECTS = ((918, 1042, 44, 20),   # 2026-09-10 레이아웃
                (905, 1030, 97, 24))   # 2026-09-13 시프트 레이아웃(253/253 실측)
HP_MAX_RECTS = ((963, 1042, 46, 20),
                (1018, 1030, 57, 24))
# 'HP : 247/253' 전체를 한 번에 담는 합본 rect 후보(BTS-1033412). 분리
# 크롭이 얇은 '7'을 잘라먹을 때의 폴백이라 넉넉한 여백을 준다. 실측
# (2026-09-13 사막던전4층) 세 변형 모두 '247/253'을 정확히 읽었다.
HP_PAIR_RECTS = ((928, 1024, 100, 20),
                 (926, 1023, 104, 22),
                 (905, 1030, 170, 24))
# HUD HP 게이지: 트랙 334px 실측(2026-09-07). 게이지 막대 위치는 스트림
# 레이아웃에 따라 y1004와 y1028 두 곳에서 관측됐다(2026-09-09 재접속 후
# 약 +24px 시프트) → 고정 rect 대신 밴드에서 막대 성분을 찾는다.
HP_GAUGE_BAND = (700, 980, 520, 130)
HP_GAUGE_TRACK = 334.0
# HUD가 막대 위에 겹쳐 쓰는 `HP : 247/253` 글자가 빨간 채움을 끊는 최대 폭
# (실측 37px). 이 폭까지만 이어붙이고, 더 먼 빨간 픽셀은 막대로 보지 않는다.
# BTS-1033358: 실측 37px에 비해 60px는 과도한 여유였다(막대 밖 빨강까지
# 사정권에 들어옴) → 실측 + 여유 8px로 좁힌다.
HP_GAUGE_GAP_TOL = 45
# 갭 건너편을 '막대 채움'으로 인정할 최소 높이 비율. 채움은 막대 높이를
# 꽉 채우므로(29/29행) 0.70이면 통과하고, 이름표/데미지 숫자 같은 얇은
# 빨강(실측 5행)은 탈락한다. BTS-1033358.
HP_GAUGE_FILL_RATIO = 0.70
# zone 텍스트(2026-09-09 라이브 실측): 우상단 HUD에 지역종류가 뜬다.
# 마을 "Safety Zone"은 파란 글씨, 필드 "Normal Zone"은 흰 글씨. 재접속
# 후 레이아웃이 약 +22px 내려가 두 위치가 모두 존재한다 → 후보 rect를
# 순서대로 시도한다. 예전 ZONE_RECT(1765,995)는 한 칸 아래 빈 영역을
# 보고 있어 항상 판독 실패했다(관측: 'a'/'OS'만 반환).
ZONE_RECTS = ((1762, 963, 166, 34),   # 마을 파랑(아이콘 제외 폭)
              (1735, 984, 190, 32),   # 필드 흰색(재접속 레이아웃)
              (1735, 962, 186, 36))   # 필드 흰색(기존 레이아웃)
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
    """분모/슬래시가 없거나 범위를 벗어난 OCR은 추측하지 않는다.

    접두어는 첫 글자 누락/대소문자 오독('HP'→'Pp')까지 허용한다.
    HP/MP 영역은 고정 크롭이라 다른 텍스트가 섞이지 않는다.
    """
    match = re.fullmatch(rf"\s*[{label[0]}]?[{label[1]}][{label[1]}]?\s*:?\s*"
                         r"(\d+)\s*/\s*(\d+)\s*", text, flags=re.IGNORECASE)
    if not match:
        return None
    current, maximum = map(int, match.groups())
    if maximum <= 0 or current > maximum:
        return None
    return current / maximum


def hp_from_gauge(img):
    """HUD HP 게이지(빨간 채움 막대) 폭으로 HP 비율을 즉시 판독한다.

    트랙 334px 실측(5샘플 일관, 오차 ±1~5%). fixture 실측(2026-09-13,
    HP 202/244): 진짜 막대 = (x57,y60,w279,h29) → 279/334=0.835, OCR
    0.828과 일치. 그 위 6px 테두리 하이라이트 = (x59,y53,w~237,h6)는
    HP와 무관한 성분 — 종전 필터(3<=h<=14, w/h>=15)는 h29 막대를 버리고
    이 h6 하이라이트를 잡아 항상 0.70에 고착시켰다(BTS-1033250).
    진짜 막대만 잡도록 높이 22~45(하이라이트/글자 배제) + w/h 상한 15
    (하이라이트 w/h≈39 이중 배제)로 잡는다. 막대가 없으면 None.

    막대 위에는 HUD가 `HP : 247/253` 글자를 겹쳐 그려서 빨간 채움이
    조각난다. 가장 넓은 조각만 쓰면 글자 오른쪽 채움을 버려
    만피(247/253=0.976)를 0.73으로 읽고 물약을 헛먹었다. 그래서 본체의
    세로 범위만 컬럼 프로파일로 훑어 오른쪽 끝을 찾고, 글자 폭만큼의
    갭(실측 37px, 여유 포함 GAP_TOL)만 이어붙인다. 멀리 떨어진 빨간
    장식은 갭 상한을 넘겨 제외되므로 과대평가(=물약 미투입)로 가지 않는다.
    """
    region = crop(img, HP_GAUGE_BAND)
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, (0, 150, 120), (10, 255, 255)) | \
        cv2.inRange(hsv, (170, 150, 120), (180, 255, 255))
    joined = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((1, 5), np.uint8))
    contours, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    body = None
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if width >= 40 and 22 <= height <= 45 and width / height <= 15:
            if body is None or width > body[2]:
                body = (x, y, width, height)
    if body is None:
        return None
    bx, by, bw, bh = body
    rows = red[by:by + bh, :]
    cols = (rows > 0).sum(axis=0)
    # 막대 채움은 막대 높이를 꽉 채운다(실측 29/29행). 이름표·데미지 숫자
    # 같은 유입 빨강은 훨씬 얇다(fixture 실측: 막대 끝 뒤 컬럼 5행).
    # 종전 need=bh*0.25(=7행)는 그 5행과 2행 차이라 노이즈가 조금만 밀면
    # 갭 이어붙이기가 발동해 막대 밖으로 끌려갔다(BTS-1033358).
    need = max(3, int(bh * HP_GAUGE_FILL_RATIO))
    right = bx + bw - 1
    # 글자 갭은 '한 번만' 이어붙인다. 종전 while 루프는 hop을 연쇄해서
    # GAP_TOL 간격으로 빨강이 놓여 있으면 오른쪽으로 무한히 끌려갔다.
    limit = min(cols.size, right + 2 + HP_GAUGE_GAP_TOL)
    nxt = next((p for p in range(right + 1, limit) if cols[p] >= need), None)
    if nxt is not None:
        right = nxt
        # 이어붙인 뒤로는 연속된 채움만 따라간다(새 갭은 건너지 않는다).
        while right + 1 < cols.size and cols[right + 1] >= need:
            right += 1
    # 트랙 밖으로는 절대 나가지 않는다. 종전에는 walk가 트랙을 넘어도
    # min(1.0)이 만피로 뭉개서 '물약 미투입 → 사망' 방향으로 숨었다.
    right = min(right, bx + int(HP_GAUGE_TRACK) - 1)
    return float(min(1.0, (right - bx + 1) / HP_GAUGE_TRACK))


# 한 프레임에 이보다 크게 떨어지면 OCR 오독으로 보고 한 프레임 유보한다.
HP_DROP_GUARD = 0.30
# OCR이 끊겨도 이 시간까지는 마지막 유효값을 쓴다. 넘으면 None(물약 보류).
HP_STALE_SEC = 1.5
# OCR과 게이지가 이 간격 이상 벌어지면 OCR 오독으로 보고 게이지를 취한다.
# 라이브 실측(2026-09-13): 206/244가 한 프레임 20/244(0.083)로 오독 —
# 게이지 0.83과 0.75 벌어졌다. 정상 프레임의 OCR-게이지 차는 ±0.01 이내.
HP_CROSS_GUARD = 0.15
# BTS-1033358: HP는 회복 이벤트(물약/귀환/힐) 없이 오를 수 없다. 따라서
# 급상승은 급락보다 더 확실한 오독 신호인데 종전에는 가드가 하락에만 있어
# 무검증 통과했다(라이브 실측: 22초간 회복 없이 0.754 → 0.874, +0.12).
# 자연 재생은 프레임(약 0.7초)당 1% 미만이라 0.08이면 걸리지 않는다.
HP_RISE_GUARD = 0.08
# 물약/귀환 직후에는 상승이 정상이므로 이 창 동안 상승 가드를 면제한다.
HP_RECOVERY_WINDOW_SEC = 6.0
_LAST_HP = None
_LAST_HP_TS = 0.0
_RECOVERY_UNTIL = 0.0


def note_recovery(window_s=None):
    """회복 이벤트(물약 사용/귀환/힐) 발생을 판독기에 알린다.

    이 호출 뒤 window_s 동안은 HP 상승 가드를 면제한다. 호출을 빠뜨리면
    정상 회복분이 한 프레임 유보될 뿐이라 안전 방향으로만 틀린다. 단
    potion_keys처럼 '단일 판독으로 회복 여부를 판정'하는 호출부는 반드시
    불러야 한다 — 유보된 상승을 '무반응'으로 오판해 물약을 2개 쓴다.
    """
    global _RECOVERY_UNTIL
    span = HP_RECOVERY_WINDOW_SEC if window_s is None else float(window_s)
    _RECOVERY_UNTIL = time.monotonic() + span
_LAST_MAX = None
_LAST_RECT_IDX = 0    # 최근 성공 HP 숫자 rect 후보 인덱스


def hp_read(img):
    """HP 비율 통합 판독. HUD 숫자(OCR) 우선 + 게이지 교차검증/폴백.

    BTS-1033250 3중 방어:
    1. 분모 점프 가드 — hp_from_hud_digits 안에서 분모(최대 HP)가 직전과
       다르면 오독으로 유보(레벨업은 다음 프레임 승인).
    2. 교차검증 — OCR과 (고쳐진) 게이지가 HP_CROSS_GUARD 이상 벌어지면
       OCR 오독으로 보고 게이지를 취한다. 종전에는 게이지가 h6 하이라이트
       를 잡는 버그가 있어 폴백을 아예 끊았으나, height 필터 수정(2026-09-13
       fixture 실측)으로 게이지가 0.835=OCR 0.828 수준으로 정확해졌다.
    3. 급락 가드 — 직전값 대비 급락(HP_DROP_GUARD 초과)은 한 프레임 유보.

    둘 다 실패하면 직전값을 HP_STALE_SEC까지 유지하고 그 뒤 None.
    호출부는 None에서 물약을 쓰지 않는다 — 모르면 추측하지 않는 쪽이 안전.
    """
    global _LAST_HP, _LAST_HP_TS
    now = time.monotonic()

    value = hp_from_hud_digits(img)
    if value is not None:
        gauge = hp_from_gauge(img)
        if gauge is not None and abs(value - gauge) > HP_CROSS_GUARD:
            value = gauge  # OCR-게이지 불일치: 게이지 쪽이 정상 경로
    else:
        # OCR 실패 → 게이지 폴백(위 교차검증 근거로 신뢰 회복)
        value = hp_from_gauge(img)

    if value is None:
        if _LAST_HP is not None and now - _LAST_HP_TS <= HP_STALE_SEC:
            return _LAST_HP
        return None

    prev = _LAST_HP
    _LAST_HP = value
    _LAST_HP_TS = now
    if prev is not None and prev - value > HP_DROP_GUARD:
        # 한 프레임만의 급락은 OCR 자릿수 오독일 때가 많다. 이번 프레임은
        # 직전값을 유지하고, 다음 프레임에도 낮게 나오면 그때 채택된다
        # (_LAST_HP는 이미 갱신). 진짜 급락이어도 한 프레임(약 0.7초)만 늦다.
        return prev
    if (prev is not None and value - prev > HP_RISE_GUARD
            and now >= _RECOVERY_UNTIL):
        # 4. 급상승 가드(BTS-1033358) — 회복 이벤트 없이 HP가 오르는 건
        # 물리적으로 불가능하므로 오독이다. 급락 가드와 같은 '한 프레임
        # 유보' 방식이라 낮은 값에 영구히 고착되지 않는다(_LAST_HP는 이미
        # 갱신 → 다음 프레임에 같은 값이 또 나오면 그때 채택).
        return prev
    return value


def hp_from_hud_digits(img):
    """HUD HP 텍스트의 현재/최대 숫자를 분리 크롭으로 읽는다.

    CDP 창 실측(2026-09-07): 슬래시가 OCR에서 유실돼 'HP94134'처럼 붙어
    나온다. 숫자 영역을 나눠 읽으면 슬래시 없이 비율을 확정할 수 있다.

    재접속 시프트 대응(BTS-1033250): HP_CUR/HP_MAX_RECTS 후보를 순서대로
    시도한다. 최근 성공 후보를 먼저 시도해 시프트 후 프레임 낭비를 줄인다.

    분모(최대 HP) 점프 가드(BTS-1033250): 244→344처럼 분모가 한 프레임에
    바뀌면 오독으로 본다(감소 방향 244→24는 low<=high 검증이 이미 차단).
    이번 프레임은 버리고 관측값을 기록해, 다음 프레임도 같은 분모면
    (실제 레벨업) 그때 승인한다 — 급락 가드와 같은 '1프레임 유보' 철학.

    합본 폴백(BTS-1033412): 분리 크롭은 글자가 몇 px만 시프트해도 얇은
    '7'이 잘려 '247'을 '24'로 읽는다(실측 사막던전4층). 분리 후보가 전부
    실패하면 'HP : 247/253' 전체를 한 번에 읽고 슬래시로 쪼갠다 — 잘림에
    둔감하다. 둘 다 실패하면 None을 돌려 게이지 폭 측정으로 넘긴다.
    """
    global _LAST_MAX, _LAST_RECT_IDX

    def accept(low, high, idx):
        """분모 점프 가드를 적용해 비율 또는 유보(None)를 돌린다.

        호출 전에 0 < high and low <= high 를 확인해야 한다. 그 형식
        검증 실패는 '이 후보가 틀렸다'(→다음 후보 시도)이고, 여기서
        돌려주는 None은 '프레임을 유보한다'(→즉시 중단)로 뜻이 달라
        한 함수에 섞지 않는다.
        """
        global _LAST_MAX, _LAST_RECT_IDX
        if _LAST_MAX is not None and high != _LAST_MAX:
            _LAST_MAX = high   # 관측은 기록(다음 프레임 일치 시 승인)
            _LAST_RECT_IDX = idx
            return None        # 분모 점프 프레임은 오독으로 유보
        _LAST_MAX = high
        _LAST_RECT_IDX = idx
        return low / high

    order = ([_LAST_RECT_IDX]
             + [i for i in range(len(HP_CUR_RECTS)) if i != _LAST_RECT_IDX])
    for idx in order:
        current = ocr(crop(img, HP_CUR_RECTS[idx]), whitelist="0123456789")
        maximum = ocr(crop(img, HP_MAX_RECTS[idx]), whitelist="0123456789")
        if not isinstance(current, str) or not isinstance(maximum, str):
            continue  # OCR 실패(None) — 다음 후보
        cs, ms = current.strip(), maximum.strip()
        if not (cs.isdigit() and ms.isdigit()):
            continue
        low, high = int(cs), int(ms)
        if not (0 < high and low <= high):
            continue           # 형식 오독 — 다음 후보 rect로 재시도
        return accept(low, high, idx)   # 유보(None)면 프레임을 버린다
    for rect in HP_PAIR_RECTS:
        text = ocr(crop(img, rect), whitelist="0123456789/")
        if not isinstance(text, str) or text.count("/") != 1:
            continue
        cs, ms = (part.strip() for part in text.split("/"))
        if not (cs.isdigit() and ms.isdigit()):
            continue
        low, high = int(cs), int(ms)
        if not (0 < high and low <= high):
            continue           # 형식 오독 — 다음 합본 후보로 재시도
        return accept(low, high, _LAST_RECT_IDX)
    return None


def zone_kind(text):
    """첫 단어(safety/normal/combat)는 정확히 일치해야 하고 뒤의 zone 변형만
    실물 오독(zoHe/cone)을 허용한다. 첫 단어가 깨지면 unknown으로 차단한다."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    if not words:
        return "unknown"
    head, tail = words[0], "".join(words[1:])
    zone_like = tail.startswith(("zone", "cone", "zo", "z0ne"))
    if head in {"safety", "satety", "safey", "satefy",
                "satcty", "salety"} and zone_like:
        # satcty/salety: 2026-09-09 라이브 "Safety Zone" 파랑 텍스트 오독 실측
        return "safe"
    if head in {"normal", "combat", "normial", "nornial", "gomibat"} and zone_like:
        # normial/nornial/gomibat: 필드 지역 텍스트 오독 실측(관찰/전투 프레임)
        return "combat"
    return "unknown"


def _zone_ocr(img, rect):
    """지역 텍스트 한 rect 판독 — 파랑(마을)+밝은색(필드) 통합 잉크 마스크."""
    region = crop(img, rect)
    channels = region.astype(np.int16)
    blue = ((channels[:, :, 0] - channels[:, :, 2] > 25)
            & (channels[:, :, 0] - channels[:, :, 1] > 10)
            & (channels[:, :, 0] > 90))
    bright = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY) > 165
    if int((blue | bright).sum()) < 120:
        return ""  # 잉크 부족 = 판독 포기(빈 화면을 텍스트로 옮기는 것 방지)
    mask = (blue | bright).astype(np.uint8) * 255
    enlarged = cv2.resize(255 - mask, None, fx=4, fy=4,
                          interpolation=cv2.INTER_LINEAR)
    enlarged = cv2.dilate(enlarged, np.ones((2, 2), np.uint8))
    return ocr(enlarged, scale=1)


def _zone_direct_ocr(img, rect):
    """밝은 배경(하늘 등) 전용: 마스크 없이 tesseract 자체 이진화에 맡긴다.
    전투 중 "Combat Zone"(흰 글씨=밝은 하늘)은 잉크 마스크가 실패하지만
    이 경로로 은힌다(2026-09-09 실측: 'Gomibat zone')."""
    region = crop(img, rect)
    enlarged = cv2.resize(region, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    return ocr(enlarged, lang="eng", scale=1)


def zone_read(img):
    """지역 텍스트를 읽는다. 마을(파랑)/필드(흰색)×레이아웃 2종 후보 rect를
    순서대로 시도하고, 잉크 마스크가 실패하면 직접 OCR로 재시도한다."""
    text = ""
    for rect in ZONE_RECTS:
        text = _zone_ocr(img, rect)
        if zone_kind(text) != "unknown":
            return text
        direct = _zone_direct_ocr(img, rect)
        if zone_kind(direct) != "unknown":
            return direct
    return text


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


def scan_drops(img):
    """화면에서 줍기 가능한 드랍(밝은 아이템 군집) 후보를 찾는다.

    실측(2026-09-07): 드랍 색상은 관측마다 달라 색 지정이 불안정하고
    점멸도 없다. 밝기 군집(드랍은 바닥보다 밝게 뭉친다)으로 후보를
    내고, 클릭 후 사라짐으로 실제 드랍인지 검증한다(호출부).
    """
    x0, y0, width, height = PLAY_RECT
    region = img[y0:y0 + height, x0:x0 + width]
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    bright = cv2.inRange(hsv, (0, 0, 140), (180, 255, 255))
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    contours, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    drops = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if not (60 <= area <= 2600):
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if w > 90 or h > 90:
            continue
        drops.append((x0 + x + w // 2, y0 + y + h // 2, int(area)))
    return sorted(drops, key=lambda d: -d[2])


# 몹 스프라이트 템플릿: 공격 지점 크롭을 자동 적립해 matchTemplate로
# 정지 몹까지 정확히 찾는다(차분은 움직임 없으면 놓친다).
TEMPLATE_DIR = Path(__file__).parent / "mob_templates"
TEMPLATE_SIZE = 56
TEMPLATE_MATCH_THRESHOLD = 0.62


def save_mob_template(img, x, y):
    """몹 공격 지점 크롭을 템플릿으로 적립한다. 유사 기존분은 스킵."""
    half = TEMPLATE_SIZE
    template = img[max(0, y - half):y + half, max(0, x - half):x + half]
    if template.size == 0:
        return None
    TEMPLATE_DIR.mkdir(exist_ok=True)
    for existing in TEMPLATE_DIR.glob("mob-*.png"):
        previous = cv2.imread(str(existing))
        if previous is None or previous.shape != template.shape:
            continue
        score = cv2.matchTemplate(previous, template, cv2.TM_CCOEFF_NORMED)
        if score.size and score.max() > 0.93:
            return existing.name
    name = f"mob-{int(time.time() * 1000) % 100000}.png"
    cv2.imwrite(str(TEMPLATE_DIR / name), template)
    return name


def detect_mobs(img):
    """적립된 몹 템플릿 매칭으로 몹 위치 목록을 반환한다.

    겹침 제거: 30px 격자로 대표 좌표를 하나만 남긴다.
    """
    hits = {}
    templates = list(TEMPLATE_DIR.glob("mob-*.png"))
    if not templates:
        return []
    x0, y0, width, height = PLAY_RECT
    region = img[y0:y0 + height, x0:x0 + width]
    for path in templates:
        template = cv2.imread(str(path))
        if template is None or template.shape[0] >= region.shape[0]:
            continue
        result = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
        for yy, xx in zip(*np.where(result >= TEMPLATE_MATCH_THRESHOLD)):
            center = (int(x0 + xx + template.shape[1] // 2),
                      int(y0 + yy + template.shape[0] // 2))
            hits[(center[0] // 30, center[1] // 30)] = (center[0], center[1], path.name)
    return list(hits.values())


# 템플릿 실패(공격해도 안 죽는 배경) 기록. 2회 실패 시 템플릿을 삭제한다.
_template_failures = {}


def mark_template_result(name, killed):
    """템플릿 공격 결과를 기록해 배경 오탐 템플릿을 자동 제거한다."""
    if killed:
        _template_failures.pop(name, None)
        return False
    count = _template_failures.get(name, 0) + 1
    _template_failures[name] = count
    if count >= 2:
        target = TEMPLATE_DIR / name
        if target.exists():
            target.unlink()
            _template_failures.pop(name, None)
            return True
    return False


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


def mob_hp_bars(img):
    """타겟 몹 머리 위 노란 HP 막대를 찾는다. 전투 지속/종료 판별용.

    실측(2026-09-07): 몹 클릭(타겟) 시 머리 위 이름표와 노란 HP 게이지가
    표시되고, 처치 후 사라진다. 빨간 캐릭터 HP바/채팅 텍스트와 구분된다.
    """
    x0, y0, _, _ = GAME_RECT
    region = crop(img, GAME_RECT)
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(hsv, (20, 120, 150), (35, 255, 255))
    yellow = cv2.morphologyEx(yellow, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    contours, _ = cv2.findContours(yellow, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    bars = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if 30 <= w <= 170 and 3 <= h <= 12 and w / h >= 4:
            bars.append((x0 + x + w // 2, y0 + y, int(w)))
    return bars


# 사용자 지시(2026-09-07): 돌골렘은 때리지 않는다.
FORBIDDEN_MOBS = {"돌골렘"}
DANGEROUS_BAR_WIDTH = 135  # HP 막대가 이보다 길면(강한 몹) 이름 확인 전에도 이탈


def mob_name_at(img, bar_center):
    """몹 HP 막대 위 이름표를 OCR한다. 실패 시 None."""
    x, y = bar_center[:2]
    text_area = img[max(0, y - 40):max(20, y - 8), max(0, x - 110):x + 110]
    if text_area.size == 0:
        return None
    text = ocr(text_area, lang="kor")
    return re.sub(r"\s+", "", text) or None


def forbidden_mob_check(img):
    """타겟 몹이 금지 몹(돌골렘 등)인지 판정한다. (금지 여부, 근거 텍스트)."""
    for bar in mob_hp_bars(img):
        if bar[2] >= DANGEROUS_BAR_WIDTH:
            return True, f"HP막대 길이 {bar[2]}px (강한 몹)"
        name = mob_name_at(img, bar)
        if name and any(word in name for word in FORBIDDEN_MOBS):
            return True, name
    return False, None


def aden_drop_at(img, x, y, previous=None):
    """드랍 위치가 아덴(깜빡이는 금색 코인)인지 확인한다. 잡템 방지용.

    금색만 보면 밝은 흙바닥이 오탐된다(실측). 아덴은 반짝임 애니메이션이
    있어 이전 프레임과 밝기가 변하는 금색 픽셀로 판정한다.
    """
    top, bottom = max(0, y - 22), y + 22
    left, right = max(0, x - 22), x + 22
    region = img[top:bottom, left:right]
    if region.size == 0:
        return False
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    # CDP 창 실측(2026-09-07): 아덴 코인 H12~18 S48~91 V141~165(주황 금색).
    gold = cv2.inRange(hsv, (8, 40, 130), (25, 130, 180))
    if previous is not None:
        before = previous[top:bottom, left:right]
        if before.shape == region.shape:
            blink = cv2.absdiff(region, before).max(axis=2)
            if np.count_nonzero(gold & (blink > 25)) >= 4:
                return True
    return np.count_nonzero(gold) >= 15


def analyze(img, target_profiles=None, *, require_url=True):
    profiles = validate_target_profiles(
        VERIFIED_TARGET_PROFILES if target_profiles is None else target_profiles)
    result = {"hp": None, "mp": None, "ready": False, "game_visible": False,
              "zone": "unknown",
              "safe_zone": False, "mobs": [], "candidates": [],
              "reason": "화면 크기 불일치"}
    if img is None or img.ndim != 3 or img.shape[2] != 3:
        return result
    if (img.shape[1], img.shape[0]) != WINDOW_SIZE:
        return result
    try:
        if require_url:
            url = ocr(crop(img, URL_RECT))
            if "purpleon.plaync.com/webplay/linclassic" not in url.replace(" ", ""):
                result["reason"] = "퍼플온 리니지 URL 확인 실패"
                return result
        # HP 판독 우선순위: 게이지 색상(즉시·안정) > 숫자 분리 > 텍스트.
        result["hp"] = hp_from_gauge(img)
        if result["hp"] is None:
            result["hp"] = hp_from_hud_digits(img)
        if result["hp"] is None:
            result["hp"] = parse_ratio(ocr(crop(img, HP_RECT),
                                          whitelist="HMP:0123456789/"), "HP")
        result["mp"] = parse_ratio(ocr(crop(img, MP_RECT),
                                          whitelist="HMP:0123456789/"), "MP")
        # 이동 전용 입력은 zone 판독과 무관하게 게임 화면 확인만으로 허용한다.
        result["game_visible"] = result["hp"] is not None and result["hp"] > 0
        zone = zone_kind(zone_read(img))
        result["zone"] = zone  # safe/combat/unknown 원값 — 판독 실패와 필드를 구분
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
