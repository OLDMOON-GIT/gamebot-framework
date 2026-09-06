"""상점 닫기: Cancel 클릭 후 확인."""
import os
import sys
import time

sys.path.insert(0, r"C:\Users\moony\linc-bot")
import cv2

from wincap import client_size, find_window, grab_window
import ctypes
import ctypes.wintypes as wt

user32 = ctypes.windll.user32
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


def mouse_abs(x, y, flags):
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    extra = wt.ULONG(0)
    inp = INPUT(type=0, mi=MOUSEINPUT(int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1)),
                                      0, flags | MOUSEEVENTF_ABSOLUTE, 0, ctypes.pointer(extra)))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


hwnd, rect = find_window("Lineage Classic")
user32.ShowWindow(hwnd, 9)
user32.SetForegroundWindow(hwnd)
time.sleep(0.5)

cw, ch = client_size(hwnd)
off_x = (rect[2] - rect[0] - cw) // 2
off_y = (rect[3] - rect[1]) - ch - off_x
# Cancel 버튼 (클라이언트 398,610)
sx = rect[0] + off_x + 398
sy = rect[1] + off_y + 610
mouse_abs(sx, sy, MOUSEEVENTF_MOVE)
time.sleep(0.1)
mouse_abs(sx, sy, MOUSEEVENTF_LEFTDOWN)
time.sleep(0.05)
mouse_abs(sx, sy, MOUSEEVENTF_LEFTUP)
time.sleep(1.5)

img = grab_window(hwnd, rect)
cv2.imwrite(os.path.join(OUT, "after-close.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
open(os.path.join(OUT, "close-result.txt"), "w").write(f"clicked ({sx},{sy})")
print("CLOSE_DONE")
