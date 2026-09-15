"""F4 스마트 줍기 — 박스(드랍) 감지, 사냥 후 반경 내 줍기.

사용자 지시(2026-09-16): 드랍은 박스 형태(아데나/순간이동 주문서 등).
반경 안 박스를 **사냥(접적)이 끝난 후** F4로 줍는다. 물약은 onestep 전담.
"""
import time
from pathlib import Path

import cv2
import numpy as np

from cdp_window import CdpWindow, EXT_PORT
from chat_watch import pickup_count
from linux_vision import find_character, red_name_candidates
from user_gate import user_active

RUNTIME = Path("/tmp/linc-bot-linux")
STOP = RUNTIME / "stop-aden"
NEAR_BOX_RADIUS = 130   # 줍기 시도 반경(px)
NEAR_MOB_RADIUS = 350   # 접적(사냥 중) 판정 반경
RETRY_GAP = 3.0


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def detect_boxes(img):
    """바닥 드랍 박스(상자 아이콘) 목록: (중심x, 하단y)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    brown = cv2.inRange(hsv, (8, 90, 90), (25, 220, 220))
    brown = cv2.morphologyEx(brown, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, _l, stats, _c = cv2.connectedComponentsWithStats(brown)
    out = []
    for i in range(1, n):
        x, y, ww, hh, a = stats[i]
        if 8 <= ww <= 45 and 6 <= hh <= 40 and 0.6 <= ww / max(hh, 1) <= 1.8 and a >= 60:
            out.append((int(x + ww / 2), int(y + hh)))
    return out


def main():
    STOP.unlink(missing_ok=True)
    w = CdpWindow(port=EXT_PORT)
    picked = 0
    log("스마트 줍기 시작(박스 감지 · 사냥 후 반경 내 F4)")
    while not STOP.exists():
        try:
            if not w.active():
                time.sleep(5)
                continue
            img = w.capture()
            char = find_character(img)
            if char is None:
                time.sleep(1.5)
                continue
            cx, cy = char[:2]
            # 접적(근처 몹) 중엔 줍지 않는다 — 사냥이 끝난 후에만.
            near_mob = any((x - cx) ** 2 + (y - cy) ** 2 <= NEAR_MOB_RADIUS ** 2
                           for x, y, _a, _r in red_name_candidates(img))
            if near_mob:
                time.sleep(1.0)
                continue
            boxes = detect_boxes(img)
            near = [b for b in boxes
                    if (b[0] - cx) ** 2 + (b[1] - cy) ** 2 <= NEAR_BOX_RADIUS ** 2]
            if not near:
                time.sleep(2.0)
                continue
            waited = 0
            while user_active() and waited < 6 and not STOP.exists():
                time.sleep(1.0)
                waited += 1
            before = pickup_count(img, w)
            w.key("F4", w.geometry())
            time.sleep(1.2)
            gain = max(0, pickup_count(w.capture(), w) - before)
            if gain:
                picked += gain
                log(f"F4 줍기 획득 {gain} (누적 {picked})")
            else:
                log(f"F4 무반응(반경 내 {len(near)}개) — {RETRY_GAP}s 후 재시도")
                time.sleep(RETRY_GAP)
        except SystemExit:
            break
        except Exception as exc:
            log(f"오류: {exc} — 재접속")
            time.sleep(5)
            try:
                w.close()
            except Exception:
                pass
            try:
                w = CdpWindow(port=EXT_PORT)
            except Exception:
                pass
    log(f"종료 — 줍기 성공 {picked}")


if __name__ == "__main__":
    main()
