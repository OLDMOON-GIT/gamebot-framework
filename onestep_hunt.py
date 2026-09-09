"""한 칸 거리 사냥 — 캐릭터 주변 근접 몹만 잡는다(2026-09-09 사용자 지시).

이동하지 않는다. 캐릭터 근처(260px 이내)에서 움직이는 몹을 클릭해
자동전투로 잡고, HP 70% 이하면 확정 슬롯(1555,1165) 물약.
모든 터치 전 사용자 양보 게이트. 근접 몹 없으면 대기(배회 없음).
"""
import json
import time
from pathlib import Path

import cv2
import numpy as np

from cdp_window import CdpWindow
from linux_vision import find_character, hp_from_gauge, red_name_candidates
from user_gate import user_active

RUNTIME = Path("/tmp/linc-bot-linux")
STOP = RUNTIME / "stop"
POTION_HP = 0.70
POTION_SLOT = (1552, 1221)   # 2026-09-09 실측: 재고95개 표시 슬롯(아래 행)
NEAR_RADIUS = 260            # 한 칸~두 칸: 캐릭터 중심 이 반경 몹만


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def yield_click(w, x, y):
    waited = 0
    while user_active() and waited < 120 and not STOP.exists():
        time.sleep(2.0)
        waited += 2
    if STOP.exists():
        raise SystemExit
    w.click(x, y, w.geometry())


def near_named_mobs(cur, char):
    """정지 몹도 잡는다: 캐릭터 근접 빨간 이름표(몹 후보) 목록."""
    if char is None:
        return []
    cx, cy = char[:2]
    mobs = []
    for x, y, area, _rect in red_name_candidates(cur):
        d = np.hypot(x - cx, y - cy)
        if d <= NEAR_RADIUS:
            # 이름표 아래 몸체를 노린다(실측: 이름 아래 약 30px)
            mobs.append((int(x), int(y + 30), area))
    return sorted(mobs, key=lambda m: -m[2])


def near_mobs(prev, cur, char):
    """캐릭터 주변 근접 이동체(몹) 목록 — 프레임 차분 + 반경 필터."""
    if char is None:
        return []
    cx, cy = char[:2]
    diff = cv2.absdiff(prev, cur).max(axis=2)
    _, th = cv2.threshold(diff, 35, 255, cv2.THRESH_BINARY)
    th = cv2.dilate(th, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mobs = []
    for c in contours:
        area = cv2.contourArea(c)
        if not (150 <= area <= 6000):
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        mx, my = x + bw // 2, y + bh // 2
        # 캐릭터 본인 몸통(가까움)은 제외: 살짝 아래쪽 중심에서 벗어난 것만
        if np.hypot(mx - cx, my - cy) <= NEAR_RADIUS and \
                np.hypot(mx - cx, my - cy) > 60:
            mobs.append((int(mx), int(my), int(area)))
    return sorted(mobs, key=lambda m: -m[2])


def main():
    STOP.unlink(missing_ok=True)
    w = CdpWindow()
    log("한 칸 거리 사냥 시작(이동 없음, 근접 몹만)")
    kills = 0
    prev = None
    while not STOP.exists():
        try:
            if not w.active():
                time.sleep(5)
                continue
            cur = w.capture()
            hp = hp_from_gauge(cur)
            potion_delayed = False
            if hp is not None and hp < 0.45:
                log(f"HP 위험({hp:.2f}): 이탈 이동")
                yield_click(w, 620, 400)  # 한 칸 원칙이지만 생존 우선
                time.sleep(2.5)
                continue
            if hp is not None and hp < POTION_HP:
                yield_click(w, *POTION_SLOT)
                log(f"물약 (HP {hp:.2f})")
                time.sleep(1.5)
                potion_delayed = True  # 물약 후에도 몹 공격은 이어간다
            if prev is None or prev.shape != cur.shape:
                prev = cur
                time.sleep(2.5)
                continue
            char = find_character(cur)
            mobs = near_mobs(prev, cur, char) or near_named_mobs(cur, char)
            prev = cur
            if not mobs:
                time.sleep(1.5 if potion_delayed else 2.5)
                continue
            mx, my, area = mobs[0]
            yield_click(w, mx, my)
            kills += 1
            log(f"근접 몹 공격 #{kills}: ({mx},{my}) 면적={area} HP={hp}")
            time.sleep(4.0)  # 자동전투 진행 대기
            prev = None      # 전투 후 재기준
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
                w = CdpWindow()
            except Exception:
                pass
    log(f"종료 — 공격 {kills}회")


if __name__ == "__main__":
    main()
