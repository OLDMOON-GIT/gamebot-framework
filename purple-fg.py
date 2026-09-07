"""PURPLE 창 포그라운드 후 화면 캡처."""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

sys.path.insert(0, r"C:\Users\moony\linc-bot")
import cv2
import numpy as np

from wincap import BITMAPINFOHEADER, find_window

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
OUT = r"C:\Users\moony\linc-bot\debug"

hwnd, rect = find_window("PURPLE")
user32.ShowWindow(hwnd, 9)
user32.SetForegroundWindow(hwnd)
time.sleep(1.5)
hwnd, rect = find_window("PURPLE")
left, top, right, bottom = rect
w, h = right - left, bottom - top
hdc = user32.GetDC(None)
mem = gdi32.CreateCompatibleDC(hdc)
bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
gdi32.SelectObject(mem, bmp)
gdi32.BitBlt(mem, 0, 0, w, h, hdc, left, top, 0x00CC0020)
bmi = BITMAPINFOHEADER()
bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
bmi.biWidth, bmi.biHeight = w, -h
bmi.biPlanes, bmi.biBitCount = 1, 32
buf = (ctypes.c_ubyte * (w * h * 4))()
gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), 0)
gdi32.DeleteObject(bmp)
gdi32.DeleteDC(mem)
user32.ReleaseDC(None, hdc)
img = np.frombuffer(buf, np.uint8).reshape(h, w, 4)[:, :, :3]
cv2.imwrite(os.path.join(OUT, "purple-fg.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 88])
open(os.path.join(OUT, "purple-fg-result.txt"), "w").write(f"OK {w}x{h} fg={user32.GetForegroundWindow()}")
print("OK")
