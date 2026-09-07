"""로비에서 카드 더블클릭 테스트 (Purple 리셋 1회)."""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

sys.path.insert(0, r"C:\Users\moony\linc-bot")
import cv2
import numpy as np

from wincap import BITMAPINFOHEADER, find_window

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
OUT = r"C:\Users\moony\linc-bot\debug"
CARD_TPL = r"C:\Users\moony\linc-bot\linc-card-template.png"
LOGO_TPL = r"C:\Users\moony\linc-bot\linc-logo-template.png"

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_WHEEL = 0x0800


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("mi", MOUSEINPUT)]


def mi(x, y, data, flags):
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    extra = wt.ULONG(0)
    absfl = MOUSEEVENTF_ABSOLUTE if flags != MOUSEEVENTF_WHEEL else 0
    if flags != MOUSEEVENTF_WHEEL:
        nx, ny = int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1))
    else:
        nx, ny = 0, 0
    inp = INPUT(type=0, mi=MOUSEINPUT(nx, ny, data, flags | absfl, 0, ctypes.pointer(extra)))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def click(sx, sy, double=False):
    mi(sx, sy, 0, MOUSEEVENTF_MOVE)
    time.sleep(0.08)
    for _ in range(2 if double else 1):
        mi(sx, sy, 0, MOUSEEVENTF_LEFTDOWN)
        time.sleep(0.05)
        mi(sx, sy, 0, MOUSEEVENTF_LEFTUP)
        time.sleep(0.08)


def capture():
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
    return np.frombuffer(buf, np.uint8).reshape(h, w, 4)[:, :, :3].copy(), rect


def match(img, tpl_path):
    tpl = cv2.imread(tpl_path)
    if tpl is None or img.shape[0] < tpl.shape[0] or img.shape[1] < tpl.shape[1]:
        return 0.0, None
    res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
    _, maxval, _, maxloc = cv2.minMaxLoc(res)
    return maxval, (maxloc, tpl.shape[1], tpl.shape[0])


notes = []
subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", r"C:\Users\moony\linc-bot\purple-restart.ps1"], capture_output=True)
time.sleep(16)
hwnd, rect = None, None
for _ in range(10):
    hwnd, rect = find_window("PURPLE")
    if hwnd:
        break
    time.sleep(2)
user32.ShowWindow(hwnd, 9)
user32.SetWindowPos(hwnd, 0, 100, 50, 1400, 1000, 0x0040)
user32.SetForegroundWindow(hwnd)
time.sleep(6)
# 스크롤 4회
mi(700, 600, 0, MOUSEEVENTF_MOVE)
time.sleep(0.2)
for _ in range(4):
    mi(0, 0, -120, MOUSEEVENTF_WHEEL)
    time.sleep(0.25)
time.sleep(2)

img, rect = capture()
cv2.imwrite(os.path.join(OUT, "rl5-lobby.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
cv_, loc = match(img, CARD_TPL)
(mx, my), tw, th = loc
tx, ty = rect[0] + mx + tw // 2, rect[1] + my + th // 2
notes.append(f"card={cv_:.2f} dblclick=({tx},{ty})")
click(tx, ty, double=True)
time.sleep(6)
img2, _ = capture()
cv2.imwrite(os.path.join(OUT, "rl5-page.jpg"), img2, [cv2.IMWRITE_JPEG_QUALITY, 85])
lv, _ = match(img2, LOGO_TPL)
notes.append(f"logo={lv:.2f}")
open(os.path.join(OUT, "rl5-result.txt"), "w", encoding="utf-8").write("\n".join(notes))
print("\n".join(notes))
