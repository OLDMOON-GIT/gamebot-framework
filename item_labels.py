"""바닥 아이템 라벨 검출 (SPEC-1032722)

리니지 클래식의 바닥 드랍 아이템은 이름 라벨로 표시된다.
라벨 특징: 흰색 테두리 사각형(상/하단 수평선) + 내부 어두운 글씨.

기존 aden_picker 의 '밝은 픽셀 군집' 휴리스틱은 글씨가 어둡기 때문에
라벨을 잡지 못했다. 여기서는 테두리 수평선 쌍을 찾아 검출한다.

좌표는 모두 캡처 이미지 픽셀 기준(창 좌상단 원점).
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# 줍기 판독 영역 (x0, y0, x1, y1) — 캡처 정규화 좌표계 1933x1332 기준.
# linux_vision.PLAY_RECT(몹 사냥용)보다 위/왼쪽을 넓게 잡는다: 드랍 라벨은
# 사냥 영역 밖(상단)에도 뜨기 때문(실측: y=181 라벨이 PLAY_RECT top=220에 잘림).
# 우측 1800 이상은 스킬 아이콘 바, 하단 980 이상은 HUD라 오탐원이므로 제외한다.
# 기본 탐색 영역. 구값 (340,45,1800,980)은 런처 패널 영역까지 걸쳐 있어
# 게임 밖을 뒤졌다. game_area.pick_rect(win)로 런타임 계산하는 것이 정확하고,
# 아래 값은 그 폴백이다. (2026-09-27 실측: video (968,356,1930,1019))
PICK_RECT = (987, 369, 1920, 860)

# 라벨 테두리 판정 파라미터
BORDER_THRESH = 200      # 테두리 흰색 최소 밝기
MIN_W, MAX_W = 40, 240   # 라벨 폭 허용 범위(px)
MIN_H, MAX_H = 18, 40    # 상/하단 테두리 간격(px)
MAX_LINE_H = 5           # 수평선으로 인정할 최대 두께(px)
DEDUP_X_TOL = 12         # 중복 라벨 판정 — 중심 x 허용 오차
DEDUP_Y_TOL = 12         # 중복 라벨 판정 — 하단 y 허용 오차
# 어두운 배경 위 테두리는 일부만 임계값을 넘어 끊긴다(실측: 하단 135px, 상단 54px).
# 따라서 상/하단 폭 일치를 요구하지 않고, 짧은 선이 긴 선 구간에 포함되는지로 판정한다.
CONTAIN_MIN = 0.8        # 짧은 선이 긴 선 x구간에 포함되어야 하는 최소 비율
# 다만 포함관계만 보면 40px 잡선이 무관한 240px 선(6배)과 쌍이 되어 중심이 100px
# 가까이 밀린다. 실측 최악 끊김이 2.5배(135/54)이므로 3배까지만 허용한다.
MAX_W_RATIO = 3.0        # 상/하단 선 길이 비 상한
PICK_DY = 18             # 라벨 하단에서 실제 아이템까지의 세로 오프셋


@dataclass(frozen=True)
class ItemLabel:
    """검출된 아이템 라벨 하나."""
    cx: int          # 라벨 중심 x
    bottom: int      # 라벨 하단 y
    w: int           # 라벨 폭
    h: int           # 라벨 높이
    name: str = ""   # 라벨 이름 OCR(등급 판별용 — 비어 있으면 미판독)

    @property
    def click(self) -> tuple[int, int]:
        """실제로 클릭해야 할 지점(라벨 바로 아래 = 아이템 위치)."""
        return self.cx, self.bottom + PICK_DY


def detect_labels(img: np.ndarray, roi: tuple[int, int, int, int]) -> list[ItemLabel]:
    """이미지에서 아이템 라벨을 검출한다.

    Args:
        img: BGR 캡처 이미지
        roi: (x0, y0, x1, y1) 게임 화면 영역. UI(사이드바/HUD)는 제외해서 넘긴다.
    Returns:
        라벨 목록 (위에서 아래 순)
    """
    x0, y0, x1, y1 = roi
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    binary = (gray > BORDER_THRESH).astype(np.uint8) * 255

    # 가로로 긴 성분만 남겨 테두리 수평선을 추출
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 1))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(horizontal, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    lines: list[tuple[int, int, int]] = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if h > MAX_LINE_H or not (MIN_W <= w <= MAX_W):
            continue
        if not (x0 < x and x + w < x1 and y0 < y < y1):
            continue
        lines.append((x, y, w))

    # findContours 반환 순서는 보장되지 않는다(실측 y 내림차순). 위에서 아래로
    # 훑어야 각 라벨이 자기 바로 아래 선과 짝지어지므로 y 오름차순으로 정렬한다.
    lines.sort(key=lambda t: (t[1], t[0]))

    # 상단선 + 하단선 쌍 매칭 → 라벨 박스
    labels: list[ItemLabel] = []
    used_bottom: set[int] = set()   # 이미 어떤 라벨의 하단선으로 확정된 선
    for i, (x_top, y_top, w_top) in enumerate(lines):
        # 위 라벨의 하단선이 아래 라벨의 상단선 노릇을 하면 사이 빈 공간에
        # 유령 라벨이 생긴다. 하단선으로 쓰인 선은 상단선 후보에서 뺀다.
        if i in used_bottom:
            continue
        best: tuple[int, int, int, int, int] | None = None   # (dy, j, x, y, w)
        for j, (x_bot, y_bot, w_bot) in enumerate(lines):
            if j == i or j in used_bottom:
                continue
            dy = y_bot - y_top
            if not (MIN_H <= dy <= MAX_H):
                continue
            # 겹치는 구간이 짧은 선의 대부분을 덮어야 같은 라벨의 상/하단으로 본다
            overlap = min(x_top + w_top, x_bot + w_bot) - max(x_top, x_bot)
            if overlap < CONTAIN_MIN * min(w_top, w_bot):
                continue
            # 길이 비가 과하면 무관한 선끼리 포함된 것이다
            if max(w_top, w_bot) > MAX_W_RATIO * min(w_top, w_bot):
                continue
            # 간격 범위 안에 후보가 여럿이면 가장 가까운 선이 진짜 하단선이다
            if best is None or dy < best[0]:
                best = (dy, j, x_bot, y_bot, w_bot)
        if best is None:
            continue
        dy, j, x_bot, y_bot, w_bot = best
        # 끊긴 쪽이 아니라 온전한(더 긴) 선을 라벨 폭 기준으로 삼는다
        bx, bw = (x_bot, w_bot) if w_bot >= w_top else (x_top, w_top)
        cx = bx + bw // 2
        # 상단선이 여러 조각으로 끊기면 같은 라벨이 중복 검출되므로 제거
        if any(abs(l.cx - cx) <= DEDUP_X_TOL and abs(l.bottom - y_bot) <= DEDUP_Y_TOL
               for l in labels):
            continue
        labels.append(ItemLabel(cx=cx, bottom=y_bot, w=bw, h=dy))
        used_bottom.add(j)

    labels.sort(key=lambda l: l.bottom)
    return labels


def annotate(img: np.ndarray, labels: list[ItemLabel]) -> np.ndarray:
    """검출 결과를 그려 넣은 사본을 돌려준다(디버그용)."""
    vis = img.copy()
    for l in labels:
        cv2.rectangle(vis, (l.cx - l.w // 2, l.bottom - l.h),
                      (l.cx + l.w // 2, l.bottom), (0, 0, 255), 3)
        cv2.circle(vis, l.click, 9, (0, 255, 255), -1)
    return vis


def read_label_names(img, labels, scale=3):
    """라벨 내부 텍스트(아이템 이름)를 OCR해 name 붙인 목록을 반환한다.

    라벨은 흰 테두리 + 어두운 글씨(밝은 배경)라 tesseract 기본 극성으로
    읽힌다. OCR 실패는 name=""(unknown 취급) — 판별이 줍기를 막지 않게.
    """
    import dataclasses
    from linux_vision import ocr
    out = []
    for lab in labels:
        x0 = max(0, lab.cx - lab.w // 2 + 2)
        y0 = max(0, lab.bottom - lab.h + 2)
        crop = img[y0:lab.bottom - 2, x0:x0 + lab.w - 4]
        if crop.size == 0:
            out.append(dataclasses.replace(lab, name=""))
            continue
        big = cv2.resize(crop, None, fx=scale, fy=scale,
                         interpolation=cv2.INTER_CUBIC)
        text = ocr(big) or ""
        out.append(dataclasses.replace(lab, name=text.strip()))
    return out
