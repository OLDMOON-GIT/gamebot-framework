"""PURPLE 중앙 클릭 → 캡처 (모달 닫기 시도)."""
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

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("mi", MOUSEINPUT)]


def click(sx, sy):
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

    def mi(flags):
        extra = wt.ULONG(0)
        return INPUT(type=0, mi=MOUSEINPUT(int(sx * 65535 / (sw - 1)), int(sy * 65535 / (sh - 1)),
                                           0, flags | MOUSEEVENTF_ABSOLUTE, 0, ctypes.pointer(extra)))
    for f in (MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP):
        i = mi(f)
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(i))
        time.sleep(0.06)


hwnd, rect = find_window("PURPLE")
user32.ShowWindow(hwnd, 3)
user32.SetForegroundWindow(hwnd)
time.sleep(1.0)
w, h = rect[2] - rect[0], rect[3] - rect[1]
click(rect[0] + w // 2, rect[1] + h // 2)   # 중앙 (모달 닫기)
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
cv2.imwrite(os.path.join(OUT, "purple-click.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
open(os.path.join(OUT, "purple-click-result.txt"), "w").write(f"OK {w}x{h} mean={img.mean():.1f}")
print("OK")
