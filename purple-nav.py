"""임의 화면 좌표 클릭 후 PURPLE 창 캡처. 인자: x y [라벨]"""
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

x, y = int(sys.argv[1]), int(sys.argv[2])
label = sys.argv[3] if len(sys.argv) > 3 else "click"
wait = float(sys.argv[4]) if len(sys.argv) > 4 else 3.0


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("mi", MOUSEINPUT)]


def mouse(x, y, flags):
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    extra = wt.ULONG(0)
    inp = INPUT(type=0, mi=MOUSEINPUT(int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1)),
                                      0, flags | MOUSEEVENTF_ABSOLUTE, 0, ctypes.pointer(extra)))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


hwnd, rect = find_window("PURPLE")
user32.SetForegroundWindow(hwnd)
time.sleep(0.8)
mouse(x, y, MOUSEEVENTF_MOVE)
time.sleep(0.1)
if label != "hover":
    mouse(x, y, MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.05)
    mouse(x, y, MOUSEEVENTF_LEFTUP)
time.sleep(wait)

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
cv2.imwrite(os.path.join(OUT, f"purple-{label}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
open(os.path.join(OUT, f"purple-{label}-result.txt"), "w").write(f"clicked ({x},{y}) {w}x{h}")
print("OK", label)
