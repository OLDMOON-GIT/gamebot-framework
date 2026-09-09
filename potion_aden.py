"""물약빨기 + 아덴줍기 통합 실행기 (2026-09-09 사용자 지시).

- 물약: HP 70% 이하면 퀵슬롯 물약 클릭. 슬롯 좌표는 최초 1회 자동 학습
  (퀵슬롯 후보를 눌러 HP가 오르는 지점을 찾아 파일로 기억).
- 아덴: 화면의 밝은 드랍 군집 터치 → 사라짐 검증 → 블랙리스트(검증 로직은
  aden_picker.py 실측 이식).
- 모든 터치 전 사용자 양보 게이트: 네가 마우스 쓰는 동안 봇은 대기.
"""
import json
import time
from pathlib import Path

import cv2

from cdp_window import CdpWindow
from linux_vision import hp_from_gauge, scan_drops
from user_gate import user_active

RUNTIME = Path("/tmp/linc-bot-linux")
STOP = RUNTIME / "stop"
SLOT_PATH = RUNTIME / "potion_slot.json"
POTION_HP = 0.70  # 사용자 지정: 70%에서 물약

# 퀵슬롯 후보 격자(2x2+주변, 실측 라인 y 1150~1270 / x 1540~1700)
CANDIDATES = [(x, y) for y in (1165, 1185, 1205, 1225, 1245)
              for x in (1555, 1575, 1595, 1615, 1635, 1655)]


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def yield_click(w, x, y):
    """양보 게이트를 통과할 때만 터치한다."""
    waited = 0
    while user_active() and waited < 120:
        time.sleep(2.0)
        waited += 2
    w.click(x, y, w.geometry())


def load_slot():
    if SLOT_PATH.exists():
        try:
            data = json.loads(SLOT_PATH.read_text())
            return tuple(data["xy"])
        except (ValueError, KeyError):
    return None


def save_slot(x, y):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    SLOT_PATH.write_text(json.dumps({"xy": [x, y]}))


def learn_potion_slot(w, hp_now):
    """퀵슬롯 후보를 눌러 HP가 오르는 좌표를 찾는다(최초 1회)."""
    log(f"물약 슬롯 학습 시작 (HP {hp_now:.2f})")
    for x, y in CANDIDATES:
        if STOP.exists():
            return None
        yield_click(w, x, y)
        time.sleep(2.2)
        hp_after = hp_from_gauge(w.capture())
        if hp_after is not None and hp_after > hp_now + 0.04:
            save_slot(x, y)
            log(f"★ 물약 슬롯 확정 ({x},{y}) HP {hp_now:.2f}→{hp_after:.2f}")
            return (x, y)
        hp_now = max(hp_now, hp_after or 0)
    log("모든 후보 무반응 — 물약 재고 소진으로 판단(보급 필요)")
    return None


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
    w = CdpWindow()
    log("물약+아덴 통합 시작")
    close_leftover_panel(w)
    slot = load_slot()
    blacklist = set()
    picked = 0
    potions = 0
    no_potion_noted = False
    while not STOP.exists():
        try:
            if not w.active():
                time.sleep(5)
                continue
            img = w.capture()
            hp = hp_from_gauge(img)
            # --- 물약 ---
            if hp is not None and hp < POTION_HP:
                if slot is None:
                    slot = learn_potion_slot(w, hp)
                    if slot is None:
                        if not no_potion_noted:
                            log("물약 없음 — 보급 필요. 줍기는 계속.")
                            no_potion_noted = True
                        time.sleep(30)
                    continue
                yield_click(w, *slot)
                potions += 1
                log(f"물약 #{potions} (HP {hp:.2f})")
                time.sleep(1.5)
                continue
            no_potion_noted = False
            # --- 아덴 줍기 (검증 로직: aden_picker 실측 이식) ---
            drops = [d for d in scan_drops(img)
                     if (d[0], d[1]) not in blacklist
                     and 560 <= d[0] <= 1290 and 240 <= d[1] <= 730]
            if not drops:
                time.sleep(4)
                continue
            for dx_, dy_, _ in drops[:2]:
                yield_click(w, dx_, dy_)
                time.sleep(1.3)
            after = w.capture()
            remaining = {(d[0] // 20, d[1] // 20) for d in scan_drops(after)}
            for dx_, dy_, _ in drops[:2]:
                if (dx_ // 20, dy_ // 20) not in remaining:
                    picked += 1
                else:
                    blacklist.add((dx_, dy_))
            log(f"줍기 시도 {len(drops[:2])} (누적 {picked}, 차단 {len(blacklist)})")
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
    log(f"종료 — 줍기 {picked}, 물약 {potions}")


if __name__ == "__main__":
    main()
