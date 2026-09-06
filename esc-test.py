"""게임 창에 ESC 보내고 캡처."""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

sys.path.insert(0, r"C:\Users\moony\linc-bot")
import cv2

from wincap import find_window, grab_window

user32 = ctypes.windll.user32
OUT = r"C:\Users\moony\linc-bot\debug"


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class KINPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("ki", KEYBDINPUT)]


def send_key(vk):
    extra = wt.ULONG(0)
    for fl in (0, 2):
        inp = KINPUT(type=1, ki=KEYBDINPUT(vk, 0, fl, 0, ctypes.pointer(extra)))
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        time.sleep(0.03)


hwnd, rect = find_window("Lineage Classic")
user32.ShowWindow(hwnd, 9)
user32.SetForegroundWindow(hwnd)
time.sleep(0.5)
send_key(0x1B)  # ESC
time.sleep(3)
img = grab_window(hwnd, rect)
cv2.imwrite(os.path.join(OUT, "after-esc.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
open(os.path.join(OUT, "esc-result.txt"), "w").write(f"esc sent, mean={img.mean():.1f}")
print("ESC_DONE")
