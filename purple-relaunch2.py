"""리니지 클래식 게임 페이지 진입 (재시도 루프 + 로고 검증).

흐름: 현재 페이지 → (필요 시 뒤로) → 로비에서 카드 매칭 즉시 클릭 → 페이지 로고 검증
"""
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
CARD_TPL = r"C:\Users\moony\linc-bot\linc-card-template.png"
LOGO_TPL = r"C:\Users\moony\linc-bot\linc-logo-template.png"

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("mi", MOUSEINPUT)]


def click_screen(sx, sy):
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

    def send(flags):
        extra = wt.ULONG(0)
        inp = INPUT(type=0, mi=MOUSEINPUT(int(sx * 65535 / (sw - 1)), int(sy * 65535 / (sh - 1)),
                                          0, flags | MOUSEEVENTF_ABSOLUTE, 0, ctypes.pointer(extra)))
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        time.sleep(0.06)

    send(MOUSEEVENTF_MOVE)
    send(MOUSEEVENTF_LEFTDOWN)
    send(MOUSEEVENTF_LEFTUP)


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


def on_game_page(img):
    """리니지 클래식 로고가 페이지에 있으면 게임 페이지."""
    v, _ = match(img, LOGO_TPL)
    return v > 0.55, v


notes = []
hwnd, rect = find_window("PURPLE")
user32.ShowWindow(hwnd, 9)
user32.SetWindowPos(hwnd, 0, 100, 50, 1400, 1000, 0x0040)
user32.SetForegroundWindow(hwnd)
time.sleep(2)

for attempt in range(4):
    img, rect = capture()
    cv2.imwrite(os.path.join(OUT, f"nav2-{attempt}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    ok, v = on_game_page(img)
    notes.append(f"attempt{attempt}: logo={v:.2f}")
    if ok:
        break
    # 카드 찾아 즉시 클릭 (캡처와 클릭 사이 지연 최소)
    cv, loc = match(img, CARD_TPL)
    if cv > 0.5:
        (mx, my), tw, th = loc
        click_screen(rect[0] + mx + tw // 2, rect[1] + my + th // 2)
        notes.append(f"  card match={cv:.2f} click=({mx + tw // 2},{my + th // 2})")
        time.sleep(4)
        continue
    # 카드가 없으면 뒤로 버튼 클릭 후 재시도
    click_screen(rect[0] + 159, rect[1] + 63)
    notes.append("  back clicked")
    time.sleep(3)

img, rect = capture()
cv2.imwrite(os.path.join(OUT, "nav2-final.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
ok, v = on_game_page(img)
notes.append(f"final logo={v:.2f} page={'LINC' if ok else 'UNKNOWN'}")
open(os.path.join(OUT, "nav2-result.txt"), "w", encoding="utf-8").write("\n".join(notes))
print("\n".join(notes))
