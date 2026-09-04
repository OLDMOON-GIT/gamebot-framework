"""리니지 클래식 실행: Purple 리셋→로비→카드 클릭→로고 검증 루프 → 게임 페이지에서 실행 버튼까지."""
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
        time.sleep(0.07)

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


notes = []
for attempt in range(4):
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", r"C:\Users\moony\linc-bot\purple-restart.ps1"],
                   capture_output=True)
    time.sleep(16)
    hwnd, rect = None, None
    for _ in range(10):
        hwnd, rect = find_window("PURPLE")
        if hwnd:
            break
        time.sleep(2)
    if not hwnd:
        notes.append(f"cycle{attempt}: PURPLE not found")
        continue
    user32.ShowWindow(hwnd, 9)
    user32.SetWindowPos(hwnd, 0, 100, 50, 1400, 1000, 0x0040)
    user32.SetForegroundWindow(hwnd)
    time.sleep(6)  # 레이아웃 정착 대기

    img, rect = capture()
    cv2.imwrite(os.path.join(OUT, f"rl3-lobby-{attempt}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    cv_, loc = match(img, CARD_TPL)
    if not loc or cv_ < 0.5:
        notes.append(f"cycle{attempt}: card match={cv_:.2f} 없음")
        continue
    (mx, my), tw, th = loc
    tx, ty = rect[0] + mx + tw // 2, rect[1] + my + th // 2
    click_screen(tx, ty)
    time.sleep(6)
    img2, rect2 = capture()
    cv2.imwrite(os.path.join(OUT, f"rl3-page-{attempt}.jpg"), img2, [cv2.IMWRITE_JPEG_QUALITY, 85])
    lv, _ = match(img2, LOGO_TPL)
    notes.append(f"cycle{attempt}: card={cv_:.2f} click=({tx},{ty}) logo={lv:.2f}")
    if lv > 0.55:
        notes.append("GAME_PAGE_OK")
        break

open(os.path.join(OUT, "rl3-result.txt"), "w", encoding="utf-8").write("\n".join(notes))
print("\n".join(notes))
