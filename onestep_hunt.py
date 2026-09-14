"""한 칸 거리 사냥 — 캐릭터 주변 근접 몹만 잡는다(2026-09-09 사용자 지시).

이동하지 않는다. 캐릭터 근처(260px 이내)에서 움직이는 몹을 클릭해
자동전투로 잡고, HP 80% 미만이면 F5/F6 물약(potion_keys 공용 —
BTS-1033250로 종전 퀵슬롯 좌표 클릭은 폐지).
모든 터치 전 사용자 양보 게이트. 근접 몹 없으면 대기(배회 없음).
"""
import time
from pathlib import Path

import cv2
import numpy as np

from cdp_window import CdpWindow, EXT_PORT
from linux_vision import find_character, hp_read, red_name_candidates
from potion_keys import EXHAUSTED, USED, PotionKeys
from user_gate import user_active

RUNTIME = Path("/tmp/linc-bot-linux")
STOP = RUNTIME / "stop"
NEAR_RADIUS = 260            # 한 칸~두 칸: 캐릭터 중심 이 반경 몹만


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class UserBusy(Exception):
    """사용자가 계속 조작 중 — 이번 터치는 포기한다(강행 금지)."""


def yield_click(w, x, y, max_wait=120):
    """사용자 양보 후 클릭. 한도까지 기다려도 사용자가 손을 안 떼면 클릭하지
    않고 UserBusy 를 던진다(종전엔 120초 뒤 강행 → '또 마우스' 재발 경로)."""
    waited = 0
    while user_active() and not STOP.exists():
        if waited >= max_wait:
            raise UserBusy(f"사용자 조작 {waited}s 지속 — 터치 생략")
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
    w = CdpWindow(port=EXT_PORT)
    log("한 칸 거리 사냥 시작(이동 없음, 근접 몹만)")
    kills = 0
    hp_unread = 0
    prev = None
    potion = PotionKeys()
    while not STOP.exists():
        try:
            if not w.active():
                time.sleep(5)
                continue
            cur = w.capture()
            hp = hp_read(cur)
            potion_delayed = False
            if hp is None:
                # HP 판독 불가 = 물약/이탈 모두 무력. 이 상태로 몹을 치면
                # 사망 경로다(리뷰). 공격 보류, 지속 시 사망 방지 중단.
                hp_unread += 1
                if hp_unread >= 12:
                    log("HP 판독 불가 지속 — 사냥 중단(사망 방지)")
                    break
                log(f"HP 판독 불가({hp_unread}/12): 공격 보류")
                time.sleep(2.5)
                continue
            hp_unread = 0
            if hp < 0.45:
                log(f"HP 위험({hp:.2f}): 이탈 이동")
                yield_click(w, 620, 400)  # 한 칸 원칙이지만 생존 우선
                time.sleep(2.5)
                continue
            result = potion.check(w, hp)
            if result == EXHAUSTED:
                log("물약 재고 소진 — 사냥 중단(사망 방지)")
                break
            potion_delayed = result == USED  # 물약 후에도 몹 공격은 이어간다
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
        except UserBusy as exc:
            log(str(exc))
            prev = None
            time.sleep(2.5)
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
    log(f"종료 — 공격 {kills}회")


if __name__ == "__main__":
    main()
