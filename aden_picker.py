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
from linux_vision import find_character, red_name_candidates
from user_gate import user_active

RUNTIME = Path("/tmp/linc-bot-linux")
STOP = RUNTIME / "stop-aden"
NEAR_BOX_RADIUS = 450   # 줍기 반경 — 두 칸(사용자 지시 2026-09-16)
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
    last_exp = None
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
            # 몹 처치(경험치 증가) 직후 즉시 F4(사용자 지시 2026-09-16
            # '몬스터를 죽이면 바로 f4하자') — 접적 중이라도 처치 순간 줍는다.
            exp_now = exp_count(img)
            killed = (last_exp is not None and exp_now > last_exp)
            if killed and near:
                log("몹 처치 확인 — 즉시 줍기")
            last_exp = exp_now
            if near_mob and not killed:
                time.sleep(0.5)
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
            # 사용자 지시(2026-09-16): 칼질 중에는 클릭하지 않되 이동은
            # 허용 — 비전투일 때 가장 가까운 박스 위로 클릭 이동 후 F4.
            target = min(near, key=lambda b: (b[0] - cx) ** 2 + (b[1] - cy) ** 2)
            bx, by = target
            dist = int(((bx - cx) ** 2 + (by - cy) ** 2) ** 0.5)
            if dist > 70:   # 발밑이 아니면 박스 위로 이동
                waited = 0
                while user_active() and waited < 6 and not STOP.exists():
                    time.sleep(1.0)
                    waited += 1
                w.click(bx, by, w.geometry())
                time.sleep(2.2)
                img2 = w.capture()
                c2 = find_character(img2)
                if c2 and ((bx - c2[0]) ** 2 + (by - c2[1]) ** 2) > 100 ** 2:
                    log("이동 미완 — 다시 시도")
                    time.sleep(1.5)
                    continue
            before = pickup_count(img, w)
            # 사용자 지시(2026-09-16): F4는 한 번만 누르지 말 것 — 여러 번.
            # 반경에 박스가 여러 개면 연타로 순차 줍기.
            for _f4 in range(4):
                w.key("F4", w.geometry())
                time.sleep(1.0)
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
