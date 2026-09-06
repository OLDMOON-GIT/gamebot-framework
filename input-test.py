"""PostMessage 클릭 입력 테스트: 몹 클릭 → 전후 프레임 비교."""
import os
import sys
import time

sys.path.insert(0, r"C:\Users\moony\linc-bot")
import cv2
import numpy as np

from wincap import click, client_size, find_window, grab_window

OUT = r"C:\Users\moony\linc-bot\debug"
hwnd, rect = find_window("Lineage Classic")
if not hwnd:
    open(os.path.join(OUT, "input-result.txt"), "w").write("WINDOW_NOT_FOUND")
    sys.exit(1)

before = grab_window(hwnd, rect)
cw, ch = client_size(hwnd)
# 이미지는 윈도우 전체(타이틀바 포함) → 클라이언트 좌표로 보정
bw, bh = before.shape[1], before.shape[0]
off_x, off_y = (bw - cw) // 2, bh - ch - (bw - cw) // 2  # 좌우/하단 보더 추정
# 몹 위치 (이미지 좌표 795,195 부근)
tx_img, ty_img = 795, 195
tx, ty = tx_img - off_x, ty_img - off_y
click(hwnd, tx, ty)
time.sleep(3)
after = grab_window(hwnd, rect)

diff = cv2.absdiff(before, after)
changed = float((diff.max(axis=2) > 40).mean())
cv2.imwrite(os.path.join(OUT, "input-before.jpg"), before, [cv2.IMWRITE_JPEG_QUALITY, 85])
cv2.imwrite(os.path.join(OUT, "input-after.jpg"), after, [cv2.IMWRITE_JPEG_QUALITY, 85])
open(os.path.join(OUT, "input-result.txt"), "w").write(
    f"click=({tx},{ty}) client={cw}x{ch} img={bw}x{bh} changed={changed:.4f}")
print("INPUT_TEST", changed)
