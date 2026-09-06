"""세션2(administrator) 데스크톱 정찰: 창 목록 + 전체화면 캡처 → debug 폴더에 저장."""
import ctypes
import ctypes.wintypes as wt
import os
import time

import cv2
import numpy as np

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
OUT = r"C:\Users\moony\linc-bot\debug"
os.makedirs(OUT, exist_ok=True)

# ── 창 목록 ──
results = []


@ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
def _cb(hwnd, lp):
    if user32.IsWindowVisible(hwnd):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        t = buf.value.strip()
        if t:
            r = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            results.append(f"hwnd={hwnd} [{r.left},{r.top},{r.right},{r.bottom}] {t}")
    return True


user32.EnumWindows(_cb, 0)
open(os.path.join(OUT, "windows.txt"), "w", encoding="utf-8").write("\n".join(results))

# ── 전체 화면 BitBlt 캡처 ──
w = user32.GetSystemMetrics(0)
h = user32.GetSystemMetrics(1)
hdc = user32.GetDC(None)
mem = gdi32.CreateCompatibleDC(hdc)
bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
gdi32.SelectObject(mem, bmp)
gdi32.BitBlt(mem, 0, 0, w, h, hdc, 0, 0, 0x00CC0020)  # SRCCOPY

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


bmi = BITMAPINFOHEADER()
bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
bmi.biWidth = w
bmi.biHeight = -h
bmi.biPlanes = 1
bmi.biBitCount = 32
bmi.biCompression = 0
buf = (ctypes.c_ubyte * (w * h * 4))()
gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), 0)
gdi32.DeleteObject(bmp)
gdi32.DeleteDC(mem)
user32.ReleaseDC(None, hdc)

img = np.frombuffer(buf, np.uint8).reshape(h, w, 4)[:, :, :3]
cv2.imwrite(os.path.join(OUT, "desktop.jpg"), img,
            [cv2.IMWRITE_JPEG_QUALITY, 80])
open(os.path.join(OUT, "probe-done.txt"), "w").write(
    f"{time.strftime('%H:%M:%S')} user={os.getlogin() if hasattr(os, 'getlogin') else '?'} {w}x{h}")
print("PROBE_OK", w, h)
