"""아덴/드랍 줍기 전담 — F4 줍기 단축키 방식 (BTS-1033502, 2026-09-15).

사용자 지시: 'f4가 단축키'. 드랍 라벨(item_labels)이 보이면 F4 키로
줍는다 — 마우스 클릭(이동 클릭→재클릭) 전에 없이 nomouse 정책 유지.
성공 판정은 채팅창 '획득' 메시지(chat_watch)로만 한다. 연속 실패 시
짧은 대기 후 재시도(토글형 키 연타 방지).
분업: ATS=몹 사냥, onestep=물약, 이 스크립트=F4 줍기.
"""
import time
from pathlib import Path

from cdp_window import CdpWindow, EXT_PORT
from chat_watch import pickup_count
from item_labels import PICK_RECT, detect_labels
from user_gate import user_active

RUNTIME = Path("/tmp/linc-bot-linux")
STOP = RUNTIME / "stop"
RETRY_GAP = 3.0        # 줍기 실패 후 재시도 간격(초)
FAIL_LIMIT = 3          # 연속 실패 상한 — 넘으면 긴 대기(드랍이 줍을 수
LONG_WAIT = 12.0        # 없는 상태일 수 있다: 멀리/이미 꽉 참 등)


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)



def detect_boxes(img):
    """바닥 드랍 박스(상자 아이콘) 감지 — 리니지 클래식 드랍은 이름 라벨이
    아니라 박스 형태로 떨어진다(사용자 확인 2026-09-16: 아데나/순간이동
    주문서 등). 갈색 작은 사각형 성분."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    brown = cv2.inRange(hsv, (8, 90, 90), (25, 220, 220))
    brown = cv2.morphologyEx(brown, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, labels, stats, cents = cv2.connectedComponentsWithStats(brown)
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
    fails = 0
    log("F4 아덴 줍기 시작")
    while not STOP.exists():
        try:
            if not w.active():
                time.sleep(5)
                continue
            img = w.capture()
            boxes = detect_boxes(img)
            near = [b for b in boxes
                    if (b[0] - cx) ** 2 + (b[1] - cy) ** 2 <= 130 ** 2]
            if not near:
                fails = 0
                time.sleep(2.0)
                continue

            before = pickup_count(img)
            # 사용자가 마우스로 조작 중이면 키만 스킵하고 잠시 양보
            waited = 0
            while user_active() and waited < 6 and not STOP.exists():
                time.sleep(1.0)
                waited += 1
            w.key("F4", w.geometry())
            time.sleep(2.0)
            gain = max(0, pickup_count(w.capture()) - before)
            if gain:
                picked += gain
                fails = 0
                log(f"F4 줍기 획득 {gain} (누적 {picked})")
            else:
                fails += 1
                wait = LONG_WAIT if fails >= FAIL_LIMIT else RETRY_GAP
                log(f"F4 무반응 ({fails}) — {wait}s 후 재시도")
                time.sleep(wait)
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
