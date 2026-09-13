"""물약빨기 + 아덴줍기 통합 실행기 (2026-09-09 사용자 지시).

- 물약: HP 80% 미만이면 F5, 반응 없으면 F6(공용 potion_keys 모듈 —
  종전 퀵슬롯 좌표 클릭/자동 학습 경로는 BTS-1033250로 폐지).
- 아덴: 화면의 밝은 드랍 군집 터치 → 사라짐 검증 → 블랙리스트(검증 로직은
  aden_picker.py 실측 이식).
- 모든 입력 전 사용자 양보 게이트: 네가 마우스 쓰는 동안 봇은 대기.
"""
import time
from pathlib import Path

import cv2

from cdp_window import CdpWindow, EXT_PORT
from item_labels import PICK_RECT, detect_labels
from linux_vision import hp_read
from potion_keys import EXHAUSTED, UNKNOWN, USED, PotionKeys
from user_gate import user_active

RUNTIME = Path("/tmp/linc-bot-linux")
STOP = RUNTIME / "stop"
GRID = 20          # 블랙리스트 대조용 좌표 격자 크기(px)
BLACKLIST_TTL = 60  # 블랙리스트 유효 시간(초) — 캐릭터가 이동하면 화면 좌표가
                    # 달라지므로 영구 차단하면 멀쩡한 아이템까지 막힌다.


def cell(x, y):
    """좌표를 격자 셀로 환산(미세한 흔들림 흡수)."""
    return x // GRID, y // GRID


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def yield_click(w, x, y):
    """양보 게이트를 통과할 때만 터치한다."""
    waited = 0
    while user_active() and waited < 120:
        time.sleep(2.0)
        waited += 2
    w.click(x, y, w.geometry())


def close_leftover_panel(w):
    """시작 전 열려 있을 수 있는 패널을 토글로 정리한다(최대 2회)."""
    import numpy as np
    base = w.capture()
    for _ in range(2):
        yield_click(w, 1730, 1265)
        time.sleep(1.5)
        after = w.capture()
        diff = np.count_nonzero(cv2.absdiff(base, after).max(axis=2) > 30)
        if diff < 3000:  # 더 이상 변화 없음 = 정리됨
            return
        base = after
    log("패널 정리 완료 추정")


def main():
    STOP.unlink(missing_ok=True)
    w = CdpWindow(port=EXT_PORT)
    log("물약+아덴 통합 시작")
    close_leftover_panel(w)
    potion = PotionKeys()
    blacklist = {}  # 셀 좌표 -> 차단 시각(초), TTL 경과 시 자동 해제
    picked = 0
    potions = 0
    while not STOP.exists():
        try:
            if not w.active():
                time.sleep(5)
                continue
            img = w.capture()
            hp = hp_read(img)
            # --- 물약 (F5/F6: 2프레임 확인·쿨다운·재고 소진 감지 공용) ---
            result = potion.check(w, hp)
            if result == EXHAUSTED:
                log("물약 재고 소진 — 줍기도 중단(보급 필요)")
                break
            if result == UNKNOWN:
                time.sleep(2)  # 판독 불가: 누르지 말고 잠깐 기다린다
            elif result == USED:
                potions += 1
                time.sleep(1.5)
                continue
            # --- 아덴 줍기 (드랍 이름 라벨 검출: aden_picker 실측 이식) ---
            now = time.time()
            blacklist = {k: t for k, t in blacklist.items() if now - t < BLACKLIST_TTL}
            labels = [l for l in detect_labels(img, PICK_RECT)
                      if cell(l.cx, l.bottom) not in blacklist]
            if not labels:
                time.sleep(4)
                continue
            # 가까운 것부터: 라벨이 화면 아래쪽일수록 캐릭터에 가깝다
            labels.sort(key=lambda l: -l.bottom)
            tried = labels[:2]
            for l in tried:
                yield_click(w, *l.click)
                time.sleep(1.3)
            after = detect_labels(w.capture(), PICK_RECT)
            remaining = {cell(l.cx, l.bottom) for l in after}
            for l in tried:
                key = cell(l.cx, l.bottom)
                if key in remaining:
                    blacklist[key] = time.time()
                else:
                    picked += 1
            log(f"줍기 시도 {len(tried)} (누적 {picked}, 차단 {len(blacklist)})")
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
    log(f"종료 — 줍기 {picked}, 물약 {potions}")


if __name__ == "__main__":
    main()
