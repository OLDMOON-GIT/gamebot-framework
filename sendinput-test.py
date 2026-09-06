"""SendInput 실마우스 클릭 테스트: 게임 포그라운드 → 몹 클릭 → 프레임 비교."""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

sys.path.insert(0, r"C:\Users\moony\linc-bot")
import cv2

from wincap import find_window, grab_window, client_size

user32 = ctypes.windll.user32
OUT = r"C:\Users\moony\linc-bot\debug"

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
SW_RESTORE = 9


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("mi", MOUSEINPUT)]


def mouse_abs(x, y, flags):
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    nx = int(x * 65535 / (sw - 1))
    ny = int(y * 65535 / (sh - 1))
    extra = wt.ULONG(0)
    inp = INPUT(type=0, mi=MOUSEINPUT(nx, ny, 0, flags | MOUSEEVENTF_ABSOLUTE, 0,
                                      ctypes.pointer(extra)))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def real_click(sx, sy):
    mouse_abs(sx, sy, MOUSEEVENTF_MOVE)
    time.sleep(0.05)
    mouse_abs(sx, sy, MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.03)
    mouse_abs(sx, sy, MOUSEEVENTF_LEFTUP)


hwnd, rect = find_window("Lineage Classic")
if not hwnd:
    open(os.path.join(OUT, "si-result.txt"), "w").write("WINDOW_NOT_FOUND")
    sys.exit(1)

user32.ShowWindow(hwnd, SW_RESTORE)
user32.SetForegroundWindow(hwnd)
time.sleep(0.5)

before = grab_window(hwnd, rect)
left, top = rect[0], rect[1]
off_x = (rect[2] - rect[0] - client_size(hwnd)[0]) // 2
off_y = (rect[3] - rect[1]) - client_size(hwnd)[1] - off_x
sx = left + off_x + 788
sy = top + off_y + 165
real_click(sx, sy)
time.sleep(3)
after = grab_window(hwnd, rect)

diff = cv2.absdiff(before, after)
changed = float((diff.max(axis=2) > 40).mean())
cv2.imwrite(os.path.join(OUT, "si-after.jpg"), after, [cv2.IMWRITE_JPEG_QUALITY, 85])
open(os.path.join(OUT, "si-result.txt"), "w").write(
    f"screen_click=({sx},{sy}) changed={changed:.4f} fg={user32.GetForegroundWindow()}")
print("SI_TEST", changed)
