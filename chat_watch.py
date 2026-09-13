"""채팅창 감시 — 줍기 성공 판정 (SPEC-1032722)

아이템 클릭은 '그 자리로 이동' 이고, 도착 후 재클릭해야 실제로 주워진다.
따라서 라벨이 화면에서 사라진 것은 성공 근거가 못 된다 —
캐릭터가 이동하면 화면이 스크롤돼 모든 라벨 좌표가 같이 밀리기 때문이다.

실제 성공은 채팅창에 '... 획득하였습니다' 류 메시지가 새로 뜨는 것으로만 확인된다.
여기서는 채팅 영역을 OCR 해 '획득' 을 포함한 라인 수를 세고,
클릭 전후의 증가분으로 줍기 성공을 판정한다.

좌표는 캡처 정규화 좌표계(1933x1332) 기준.
"""
from __future__ import annotations

import subprocess

import cv2
import numpy as np

# 채팅 로그 영역 (x0, y0, x1, y1).
# 좌측 HUD(스탯), 우측 스크롤바/인벤토리 아이콘은 제외한다.
# 기본 채팅 영역. 구값 (645,1090,1495,1270)은 실제 채팅 위치와 완전히 어긋나
# (실측 1140,900~1700,1020) 빈 영역만 OCR 해 획득 판정이 늘 0이었다.
# game_area.chat_rect(win)로 런타임 계산하는 것이 정확하고, 아래는 폴백이다.
CHAT_RECT = (1141, 900, 1699, 1019)

# OCR 전처리: 채팅 글씨는 어두운 배경 위 밝은 글씨라 반전 후 이진화한다.
_OCR_THRESH = 130
_OCR_SCALE = 2  # tesseract 는 작은 글씨에 약해 2배 확대

# 줍기 성공 메시지 키워드. 게임 문구는 '아데나 (68) 을(를) 획득하였습니다.' 형태.
PICKUP_KEYWORD = "획득"


def _preprocess(img: np.ndarray) -> np.ndarray:
    """채팅 영역을 잘라 OCR 하기 좋게 전처리한다."""
    x0, y0, x1, y1 = CHAT_RECT
    crop = img[y0:y1, x0:x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, _OCR_THRESH, 255, cv2.THRESH_BINARY)
    # 밝은 글씨 → 검은 글씨/흰 배경으로 반전
    binary = cv2.bitwise_not(binary)
    return cv2.resize(binary, None, fx=_OCR_SCALE, fy=_OCR_SCALE,
                      interpolation=cv2.INTER_CUBIC)


def read_chat(img: np.ndarray) -> str:
    """채팅 영역 OCR 결과 원문을 돌려준다."""
    prepped = _preprocess(img)
    ok, buf = cv2.imencode(".png", prepped)
    if not ok:
        return ""
    try:
        res = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "kor", "--psm", "6"],
            input=buf.tobytes(), capture_output=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    return res.stdout.decode("utf-8", "replace")


def pickup_count(img: np.ndarray) -> int:
    """채팅창에 보이는 '획득' 메시지 라인 수.

    절대값 자체는 의미가 없다(채팅이 스크롤되면 줄어든다).
    클릭 전후로 호출해 **증가했을 때만** 줍기 성공으로 판정할 것.
    """
    text = read_chat(img)
    return sum(1 for line in text.splitlines() if PICKUP_KEYWORD in line)


if __name__ == "__main__":
    from cdp_window import CdpWindow

    frame = CdpWindow().capture()
    print("--- 채팅 OCR ---")
    print(read_chat(frame))
    print(f"--- 획득 라인 수: {pickup_count(frame)} ---")
