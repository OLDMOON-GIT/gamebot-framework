"""아덴/드랍 줍기 전담 — ATS(게임 자동사냥)가 잡은 시체 뒷정리 (2026-09-08).

분업: ATS=몹 사냥, 이 스크립트=바닥 드랍 아이템을 터치로 줍기.
드랍은 이름 라벨(흰 테두리 + 어두운 글씨)로 표시되므로 item_labels 로 검출한다.

줍기는 2단계다: 아이템 클릭 = 그 자리로 '이동', 도착 후 재클릭 = 실제 줍기.
성공 판정은 채팅창의 '획득' 메시지(chat_watch)로만 한다.
라벨이 사라진 것은 근거가 못 된다 — 캐릭터가 이동하면 화면이 스크롤돼
모든 라벨 좌표가 같이 밀리기 때문에 거짓 성공이 대량으로 잡힌다.
"""
import time
from pathlib import Path

from cdp_window import CdpWindow, EXT_PORT
from chat_watch import pickup_count
from item_labels import PICK_RECT, detect_labels
from linux_vision import hp_read

RUNTIME = Path("/tmp/linc-bot-linux")
STOP = RUNTIME / "stop"
GRID = 20          # 블랙리스트/대조용 좌표 격자 크기(px)
BLACKLIST_TTL = 60  # 블랙리스트 유효 시간(초) — 캐릭터가 이동하면 화면 좌표가
                    # 달라지므로 영구 차단하면 멀쩡한 아이템까지 막힌다.


def cell(x, y):
    """좌표를 격자 셀로 환산(미세한 흔들림 흡수)."""
    return x // GRID, y // GRID


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def main():
    STOP.unlink(missing_ok=True)
    w = CdpWindow(port=EXT_PORT)
    blacklist = {}  # 격자셀 -> 등록시각
    picked = 0
    log("아덴 줍기 시작")
    while not STOP.exists():
        try:
            if not w.active():
                time.sleep(5)
                continue
            img = w.capture()

            now = time.time()
            blacklist = {k: t for k, t in blacklist.items() if now - t < BLACKLIST_TTL}
            labels = [l for l in detect_labels(img, PICK_RECT)
                      if cell(l.cx, l.bottom) not in blacklist]
            if not labels:
                time.sleep(4)
                continue

            # 가까운 것부터: 라벨이 화면 아래쪽일수록 캐릭터에 가깝다
            labels.sort(key=lambda l: -l.bottom)
            target = labels[0]
            key = cell(target.cx, target.bottom)
            geo = w.geometry()

            # 줍기 성공은 채팅 '획득' 메시지로만 인정한다.
            # 라벨이 사라진 것은 근거가 못 된다 — 클릭하면 캐릭터가 이동하고,
            # 이동하면 화면이 스크롤돼 모든 라벨 좌표가 함께 밀리기 때문.
            before = pickup_count(img)

            # 1단계: 아이템 위치 클릭 = 그 자리로 이동
            w.click(*target.click, geo)
            time.sleep(1.6)

            # 2단계: 이동으로 좌표가 밀렸으므로 재검출해서 가장 가까운 것을 다시 클릭 = 줍기
            moved = detect_labels(w.capture(), PICK_RECT)
            if moved:
                nearest = max(moved, key=lambda l: l.bottom)
                w.click(*nearest.click, geo)
                time.sleep(1.4)

            gain = max(0, pickup_count(w.capture()) - before)
            if gain:
                picked += gain
            else:
                blacklist[key] = time.time()
            log(f"줍기 시도 1 → 획득 {gain} (확인된 누적 {picked}, 블랙리스트 {len(blacklist)})")
            time.sleep(2)
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
