"""F4 스마트 줍기 — 박스(드랍) 감지, 사냥 후 반경 내 줍기.

사용자 지시(2026-09-16): 드랍은 박스 형태(아데나/순간이동 주문서 등).
반경 안 박스를 **사냥(접적)이 끝난 후** F4로 줍는다. 물약은 onestep 전담.
"""
import time
from pathlib import Path

import cv2
import numpy as np

from cdp_window import CdpWindow, EXT_PORT
from chat_watch import exp_count, pickup_count
from item_labels import PICK_RECT, detect_labels, read_label_names
from item_tiers import tier_of
from linux_vision import find_character, red_name_candidates
from user_gate import user_active

RUNTIME = Path("/tmp/linc-bot-linux")
STOP = RUNTIME / "stop-aden"
NEAR_BOX_RADIUS = 450   # 줍기 반경 — 두 칸(사용자 지시 2026-09-16)
NEAR_MOB_RADIUS = 350   # 접적(사냥 중) 판정 반경
RETRY_GAP = 3.0


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def two_tile_highs(char, labels, radius=NEAR_BOX_RADIUS):
    """캐릭터 두 칸(radius) 안 고급 드랍 클릭 좌표. 몽둥이 등 저급은 제외."""
    if not char:
        return []
    cx, cy = char[:2]
    out = []
    for lab in labels or []:
        if tier_of(getattr(lab, "name", "") or "") != "high":
            continue
        x, y = lab.click
        d2 = (x - cx) ** 2 + (y - cy) ** 2
        if d2 <= radius ** 2:
            out.append((d2, x, y, lab.name))
    out.sort()
    return out


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
    last_exp = None
    n_f4 = 0
    log("아덴 줍기 시작(잡템 제외 · F4)")
    while not STOP.exists():
        try:
            if not w.active():
                time.sleep(1.0)
                continue
            w.key("F4", w.geometry())
            n_f4 += 1
            picked += 1
            if n_f4 % 20 == 0:
                log(f"F4 아덴 줍기 {n_f4}회")
            if n_f4 % 8 == 0:
                img = w.capture()
                labels = read_label_names(img, detect_labels(img, PICK_RECT))
                names = [l.name for l in labels if l.name]
                highs = [n for n in names if tier_of(n) == "high"]
                lows = [n for n in names if tier_of(n) == "low"]
                if names and lows and len(lows) == len(names) and not highs:
                    log("잡템만 보임 — F4 잠시 쉼")
                    time.sleep(1.0)
                else:
                    char = find_character(img)
                    near_mob = False
                    if char:
                        cx, cy = char[:2]
                        near_mob = any(
                            (x - cx) ** 2 + (y - cy) ** 2 <= NEAR_MOB_RADIUS ** 2
                            for x, y, _a, _r in red_name_candidates(img)
                        )
                    near_high = two_tile_highs(char, labels)
                    if near_high and not near_mob:
                        _d2, x, y, name = near_high[0]
                        if _d2 > 90 ** 2:
                            # 바닥 클릭은 자동공격을 끊는다(BTS-1033742). F4만.
                            log(f"두칸 드랍 {name} — F4만(바닥클릭 금지)")
            time.sleep(0.32)
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
