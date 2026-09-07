"""미니맵 기반 단순 사냥 — 게임 맵/몹 데이터 전략(2026-09-07 사용자 지시).

화면 인식(템플릿/차분)을 버리고 게임이 주는 정보를 그대로 쓴다:
- 미니맵 빨간 점 = 몹 위치 (중심 1810,195 = 자기)
- HUD HP 게이지 = 체력 (트랙 334px)
- 터치 탭 = 이동/공격 (웹플레이는 터치 입력 소비)
- 퀵슬롯 (1590,1255) = 물약
하이네 잡밭(7시 방향)이 저레벨 몹 밀집지다(인벤 지도 데이터).
"""
import argparse
import json
import logging
import time
from pathlib import Path

from cdp_window import CdpWindow
from linux_vision import hp_from_gauge
import cv2
import numpy as np

RUNTIME = Path("/tmp/linc-bot-linux")
STOP = RUNTIME / "stop"
STATUS = RUNTIME / "status.json"
MINIMAP = (1700, 105, 220, 185)   # 미니맵 내부
CHAR_CENTER = (1810, 195)          # 미니맵 중심 = 자기 캐릭터
POTION_SPOT = (1590, 1255)         # 퀵슬롯 물약
POTION_HP = 0.70


def status(**kw):
    RUNTIME.mkdir(exist_ok=True)
    STATUS.write_text(json.dumps({"time": time.time(), **kw}, ensure_ascii=False, default=str))


def minimap_mobs(img):
    """미니맵 빨간 점(몹) 위치 목록."""
    x0, y0, w0, h0 = MINIMAP
    region = img[y0:y0+h0, x0:x0+w0]
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, (0,150,120),(10,255,255)) | cv2.inRange(hsv, (170,150,120),(180,255,255))
    red = cv2.morphologyEx(red, cv2.MORPH_OPEN, np.ones((2,2), np.uint8))
    contours, _ = cv2.findContours(red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    dots = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if 3 <= w <= 18 and 3 <= h <= 18:
            dots.append((x0+x+w//2, y0+y+h//2))
    return dots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=3500)
    args = parser.parse_args()
    STOP.unlink(missing_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler()])
    w = CdpWindow()
    deadline = time.monotonic() + args.seconds
    kills = 0
    prev_hp = None
    log = logging.getLogger("hunt")
    log.info("미니맵 사냥 시작 (중심=%s)", CHAR_CENTER)
    try:
        while time.monotonic() < deadline:
            if STOP.exists():
                log.info("중지 요청")
                break
            if not w.active():
                log.info("게임 비디오 대기(인증/로비)")
                status(running=True, kills=kills, hp=None, mode="대기")
                time.sleep(3)
                continue
            img = w.capture()
            hp = hp_from_gauge(img)
            status(running=True, kills=kills, hp=hp, mode="사냥")
            if hp is None:
                log.info("HP 판독 불가 대기")
                time.sleep(2)
                continue
            # 물약: HP 게이지 기준, 퀵슬롯 터치
            if hp < POTION_HP:
                w.click(*POTION_SPOT, w.geometry())
                log.info("물약 (HP %.2f)", hp)
                time.sleep(1.2)
                continue
            # 자동전투 중(HP 하락) 개입 금지
            if prev_hp is not None and hp < prev_hp - 0.02:
                log.info("전투 중 대기 (HP %.2f→%.2f)", prev_hp, hp)
                prev_hp = hp
                time.sleep(2.5)
                continue
            prev_hp = hp
            # 미니맵 몹
            dots = minimap_mobs(img)
            cx, cy = CHAR_CENTER
            near = [d for d in dots if abs(d[0]-cx) <= 45 and abs(d[1]-cy) <= 40]
            if near:
                # 몹이 자기 옆(미니맵 중심 부근) — 화면 중앙 근처 탭으로 공격
                kills += 1
                w.click(1150, 560, w.geometry())
                log.info("몹 인접 공격 #%s", kills)
                time.sleep(4)
                continue
            if dots:
                # 가장 가까운 몹 방향으로 이동: 미니맵 벡터 → 화면 클릭
                dx = sum(d[0]-cx for d in dots)/len(dots)
                dy = sum(d[1]-cy for d in dots)/len(dots)
                step = 260
                norm = max(abs(dx), abs(dy), 1)
                tx = int(1150 + dx/norm*step)
                ty = int(560 + dy/norm*step*0.8)
                tx = max(600, min(tx, 1300)); ty = max(260, min(ty, 730))
                w.click(tx, ty, w.geometry())
                log.info("몹 %d마리 방향 이동 (%+d,%+d)→탭(%d,%d)", len(dots), dx, dy, tx, ty)
                time.sleep(3)
                continue
            # 몹 없음: 하이네 잡밭(7시=남서) 방향 배회
            w.click(850, 700, w.geometry())
            log.info("몹 없음: 남서(잡밭) 이동")
            time.sleep(3)
    finally:
        status(running=False, kills=kills, mode="종료")
        log.info("종료, 처치 %s", kills)
        w.close()


if __name__ == "__main__":
    main()
