"""아덴/드랍 줍기 전담 — ATS(게임 자동사냥)가 잡은 시체 뒷정리 (2026-09-08).

분업: ATS=몹 사냥, 이 스크립트=화면의 드랍(밝은 아이템 군집)을 터치로 줍기.
클릭 후 사라지면 줍기 성공, 안 사라지는 바닥 오탐은 블랙리스트로 제외.
"""
import json
import time
from pathlib import Path

import cv2
import numpy as np

from cdp_window import CdpWindow
from linux_vision import hp_from_gauge, scan_drops

RUNTIME = Path("/tmp/linc-bot-linux")
STOP = RUNTIME / "stop"
POTION_SPOT = (1600, 1255)


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def main():
    STOP.unlink(missing_ok=True)
    w = CdpWindow()
    blacklist = set()
    picked = 0
    log("아덴 줍기 시작")
    while not STOP.exists():
        try:
            if not w.active():
                time.sleep(5)
                continue
            img = w.capture()
            # HP 낮으면 물약 먼저 (재고 있는 한)
            hp = hp_from_gauge(img)
            if hp is not None and hp < 0.6:
                w.click(*POTION_SPOT, w.geometry())
                log("물약 (HP %.2f)", hp) if False else log(f"물약 (HP {hp:.2f})")
                time.sleep(1.5)
                continue
            drops = [d for d in scan_drops(img)
                     if (d[0], d[1]) not in blacklist
                     and 560 <= d[0] <= 1290 and 240 <= d[1] <= 730]
            if not drops:
                time.sleep(4)
                continue
            # 상위 2개만 시도 (큰 군집=아이템 확률 높음)
            for dx_, dy_, _ in drops[:2]:
                w.click(dx_, dy_, w.geometry())
                time.sleep(1.3)
            after = w.capture()
            remaining = {(d[0] // 20, d[1] // 20) for d in scan_drops(after)}
            for dx_, dy_, _ in drops[:2]:
                if (dx_ // 20, dy_ // 20) not in remaining:
                    picked += 1
                else:
                    blacklist.add((dx_, dy_))
            log(f"줍기 시도 {len(drops[:2])} (성공 누적 {picked}, 블랙리스트 {len(blacklist)})")
            time.sleep(2)
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
    log(f"종료 — 줍기 성공 {picked}")


if __name__ == "__main__":
    main()
