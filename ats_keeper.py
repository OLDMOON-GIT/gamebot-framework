"""ATS(게임 내장 자동사냥) 감시자 — 끊기면 다시 켠다."""
import time
from pathlib import Path
import cv2
import numpy as np
from cdp_window import CdpWindow

STOP = Path("/tmp/linc-bot-linux/stop")
ACTION_BTN = (1730, 1265)
ATS_MENU = (1150, 1150)
ATS_START = (975, 850)

def log(m): print(time.strftime("%H:%M:%S"), m, flush=True)

def main():
    STOP.unlink(missing_ok=True)
    w = CdpWindow()
    prev = None
    idle = 0
    log("ATS 감시 시작")
    while not STOP.exists():
        try:
            if not w.active():
                time.sleep(10); continue
            cur = w.capture()
            active = prev is None or np.count_nonzero(
                cv2.absdiff(prev, cur).max(axis=2) > 30) > 20000
            prev = cur
            if active:
                idle = 0; time.sleep(20); continue
            idle += 1
            log(f"화면 정지 {idle}회")
            if idle >= 3:
                log("ATS 재가동")
                w.click(*ACTION_BTN, w.geometry()); time.sleep(1.5)
                w.click(*ATS_MENU, w.geometry()); time.sleep(2)
                w.click(*ATS_START, w.geometry()); time.sleep(2)
                idle = 0; prev = None
            time.sleep(15)
        except Exception as exc:
            log(f"오류: {exc}")
            time.sleep(10)
            try: w.close()
            except Exception: pass
            try: w = CdpWindow()
            except Exception: pass
    log("ATS 감시 종료")

if __name__ == "__main__":
    main()
