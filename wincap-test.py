"""Lineage Classic 창 캡처 테스트 → debug/game-win.jpg"""
import os
import sys

sys.path.insert(0, r"C:\Users\moony\linc-bot")
import cv2

from wincap import client_size, find_window, grab_window

OUT = r"C:\Users\moony\linc-bot\debug"
hwnd, rect = find_window("Lineage Classic")
if not hwnd:
    open(os.path.join(OUT, "wincap-result.txt"), "w").write("WINDOW_NOT_FOUND")
    sys.exit(1)
img = grab_window(hwnd, rect)
cw, ch = client_size(hwnd)
cv2.imwrite(os.path.join(OUT, "game-win.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
open(os.path.join(OUT, "wincap-result.txt"), "w").write(
    f"hwnd={hwnd} rect={rect} client={cw}x{ch} mean={img.mean():.1f}")
print("CAPTURE_OK", rect, img.mean())
