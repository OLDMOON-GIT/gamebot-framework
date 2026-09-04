"""프레임 분석: HP/MP 바 자동 탐지 + 몬스터 빨간 이름표 클러스터 탐지."""
import io

import cv2
import numpy as np


def decode_jpeg(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("스크린샷 디코딩 실패")
    return img


def _fill_ratio(bar_img: np.ndarray, hsv_lo, hsv_hi) -> float:
    """가로 바에서 색상 채움 비율 (열 단위: 색 픽셀이 40% 이상인 열)."""
    if bar_img.size == 0:
        return -1.0
    hsv = cv2.cvtColor(bar_img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, hsv_lo, hsv_hi)
    col = (mask > 0).mean(axis=0)
    filled = (col > 0.4).sum()
    return filled / max(1, bar_img.shape[1])


class HUD:
    """HP/MP 바 위치 자동 탐지 (좌상단 HUD). 한 번 잡히면 고정."""

    RED_LO, RED_HI = (0, 120, 100), (10, 255, 255)
    RED2_LO, RED2_HI = (170, 120, 100), (180, 255, 255)
    BLUE_LO, BLUE_HI = (95, 100, 80), (130, 255, 255)

    def __init__(self, cfg: dict):
        self.hp_rect = tuple(cfg["hud"]["hp_rect"]) if cfg["hud"]["hp_rect"] else None
        self.mp_rect = tuple(cfg["hud"]["mp_rect"]) if cfg["hud"]["mp_rect"] else None

    def _find_bar(self, img, masks, y_lo, y_hi, x_hi):
        """가로로 긴 채움 바를 탐지. (x, y, w, h) 또는 None."""
        h, w = img.shape[:2]
        region = img[int(h * y_lo):int(h * y_hi), 0:int(w * x_hi)]
        mask = np.zeros(region.shape[:2], np.uint8)
        for lo, hi in masks:
            hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
            mask |= cv2.inRange(hsv, lo, hi)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        best = None
        for c in cnts:
            x, y, bw, bh = cv2.boundingRect(c)
            if bw > 60 and bw > bh * 4 and bh >= 4:
                if best is None or bw * bh > best[2] * best[3]:
                    best = (x, y + int(h * y_lo), bw, bh)
        return best

    def calibrate(self, img):
        if self.hp_rect is None:
            self.hp_rect = self._find_bar(
                img, [(self.RED_LO, self.RED_HI), (self.RED2_LO, self.RED2_HI)],
                0.0, 0.30, 0.45)
        if self.mp_rect is None:
            self.mp_rect = self._find_bar(
                img, [(self.BLUE_LO, self.BLUE_HI)], 0.0, 0.30, 0.45)

    def ratios(self, img):
        self.calibrate(img)
        out = {"hp": -1.0, "mp": -1.0}
        if self.hp_rect:
            x, y, w, h = self.hp_rect
            bar = img[y:y + h, x:x + w]
            r1 = _fill_ratio(bar, self.RED_LO, self.RED_HI)
            r2 = _fill_ratio(bar, self.RED2_LO, self.RED2_HI)
            out["hp"] = max(r1, r2)
        if self.mp_rect:
            x, y, w, h = self.mp_rect
            bar = img[y:y + h, x:x + w]
            out["mp"] = _fill_ratio(bar, self.BLUE_LO, self.BLUE_HI)
        return out


def find_mobs(img: np.ndarray, exclude_top: float = 0.12,
              center_exclude: float = 0.06):
    """빨간 이름표(몬스터) 클러스터 탐지 → [(cx, cy, area), ...] (이름표 기준, 아래로 오프셋 필요).

    HUD/채팅 영역과 화면 중앙(내 캐릭터 이름)은 제외.
    """
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, (0, 140, 130), (8, 255, 255))
    m2 = cv2.inRange(hsv, (172, 140, 130), (180, 255, 255))
    mask = m1 | m2
    mask[:int(h * exclude_top), :] = 0          # 상단 HUD 제외
    mask[:, :int(w * 0.02)] = 0                  # 좌측 채팅 끝단
    cx, cy = w // 2, h // 2
    r = int(min(w, h) * center_exclude)
    mask[cy - r:cy + r, cx - r:cx + r] = 0      # 내 캐릭터 주변 제외
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 6), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mobs = []
    for c in cnts:
        x, y, bw, bh = cv2.boundingRect(c)
        area = cv2.contourArea(c)
        # 이름표: 가로형 텍스트 덩어리
        if 30 <= area <= 4000 and bw >= 12 and bw > bh * 1.5 and bh <= 30:
            mobs.append((x + bw // 2, y + bh // 2, int(area)))
    return mobs
