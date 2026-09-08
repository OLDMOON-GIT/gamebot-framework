"""ATS 상태 탐침 — 잔여시간 카운트다운 감소로만 상태를 판정한다.

Claude 협의(2026-09-09): 화면 움직임(absdiff)은 사용자 플레이와 ATS를
구분 못 해 상태 판정에 절대 쓰지 않는다. 판정 신호는
1) 주 : 잔여시간 숫자가 실제로 감소한다 = ATS 구동 중
2) 보조: 기동 직후 시스템 채팅 문구(단발)
판독 불가(UNKNOWN)는 ON으로 간주하지 않는다(무인 운전 금지 원칙).
"""

import re
import time

import cv2

ON = "ON"
OFF = "OFF"
UNKNOWN = "UNKNOWN"


def read_ats_seconds(frame, rect):
    """잔여시간 ROI에서 'H:MM:SS'/'MM:SS'를 읽어 초로 반환. 실패 None."""
    if frame is None or not rect:
        return None
    from linux_vision import crop, ocr
    x, y, w, h = rect
    try:
        text = ocr(crop(frame, (x, y, w, h)), whitelist="0123456789:")
    except (OSError, ValueError, RuntimeError):
        return None
    if not isinstance(text, str):
        return None
    parts = [p for p in text.split(":") if p.isdigit()]
    if not parts or len(parts) < 2:
        return None
    try:
        secs = [int(p) for p in parts[-3:]]
    except ValueError:
        return None
    total = 0
    for value in secs:
        total = total * 60 + value
    return total


class AtsProbe:
    """샘플을 모아 카운트다운 감소로 ATS 상태를 판정한다.

    판정 규칙(협의안):
    - 최근 샘플 2개가 모두 숫자이고 뒤 샘플이 앞보다 작다 → ON
    - 두 샘플이 같거나(정지) 판독 자체가 안 된다 → UNKNOWN(ON 단정 금지)
    - OFF 확정은 기동 루프에서 '기동 후에도 UNKNOWN 지속'으로만 한다.
    """

    def __init__(self, rect, max_samples=6):
        self.rect = tuple(rect) if rect else None
        self.samples = []  # (monotonic_time, seconds)
        self.max_samples = max_samples

    def observe(self, frame):
        """프레임 하나를 관찰해 상태를 반환한다."""
        if self.rect is None:
            return UNKNOWN
        seconds = read_ats_seconds(frame, self.rect)
        now = time.monotonic()
        if seconds is not None:
            self.samples.append((now, seconds))
            self.samples = self.samples[-self.max_samples:]
        if len(self.samples) < 2:
            return UNKNOWN
        (t0, s0), (t1, s1) = self.samples[-2], self.samples[-1]
        if t1 - t0 < 1.0:
            return UNKNOWN  # 간격이 너무 짧으면 카운트다운 판정 불가
        if s1 < s0:
            return ON
        return UNKNOWN

    def stale(self, seconds=120):
        """샘플이 오래 안 왔거나(판독 불가 지속) 값이 계속 같으면 진짜 꺼짐 후보."""
        if not self.samples:
            return time.monotonic() > getattr(self, "_started", time.monotonic()) + seconds
        return time.monotonic() - self.samples[-1][0] > seconds
