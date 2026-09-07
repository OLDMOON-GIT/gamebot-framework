"""PURPLE 창에 Alt+Left(뒤로) 전송 후 캡처."""
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

VK_MENU, VK_LEFT = 0x12, 0x25
KEYEVENTF_KEYUP = 2


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class KINPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("ki", KEYBDINPUT)]


def key(vk, up=False):
    extra = wt.ULONG(0)
    inp = KINPUT(type=1, ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, ctypes.pointer(extra)))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
    time.sleep(0.04)


hwnd, rect = find_window("PURPLE")
user32.SetForegroundWindow(hwnd)
time.sleep(0.8)
key(0x1B)  # ESC
key(0x1B, up=True)
time.sleep(3)

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
cv2.imwrite(os.path.join(OUT, "purple-esc.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
open(os.path.join(OUT, "purple-esc-result.txt"), "w").write(f"OK {w}x{h}")
print("OK")
