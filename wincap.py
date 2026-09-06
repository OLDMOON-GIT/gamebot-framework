"""Lineage Classic 창 캡처/입력 모듈 (세션2 administrator 컨텍스트에서 동작)."""
import ctypes
import ctypes.wintypes as wt

import cv2
import numpy as np

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
PW_RENDERFULLCONTENT = 3


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


def find_window(substr: str):
    """제목에 substr 포함된 최상위 창 (hwnd, rect) 반환."""
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def _cb(hwnd, lp):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        if substr.lower() in buf.value.lower():
            r = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            found.append((hwnd, (r.left, r.top, r.right, r.bottom)))
        return True

    user32.EnumWindows(_cb, 0)
    if not found:
        return None, None
    # 가장 큰 창 선택 (1x1 도우미 창 오탐 방지)
    hwnd, rect = max(found, key=lambda f: (f[1][2] - f[1][0]) * (f[1][3] - f[1][1]))
    return hwnd, rect


def _read_bitmap(mem, bmp, w, h):
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    buf = (ctypes.c_ubyte * (w * h * 4))()
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    return np.frombuffer(buf, np.uint8).reshape(h, w, 4)[:, :, :3].copy()


def grab_window(hwnd, rect):
    """PrintWindow 우선, 실패(검은 화면) 시 화면 BitBlt 폴백. BGR 이미지 반환."""
    left, top, right, bottom = rect
    w, h = right - left, bottom - top

    # 1) PrintWindow (가려져도 캡처 가능)
    hwnd_dc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    gdi32.SelectObject(mem, bmp)
    ok = user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT)
    img = None
    if ok:
        img = _read_bitmap(mem, bmp, w, h)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hwnd_dc)
    if img is not None and img.mean() > 8:
        return img

    # 2) 화면 BitBlt 폴백 (창이 가려지면 가려진 대로 나옴)
    hdc = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, w, h, hdc, left, top, 0x00CC0020)
    img = _read_bitmap(mem, bmp, w, h)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(None, hdc)
    return img


def _client_origin(hwnd):
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def client_size(hwnd):
    r = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    return r.right, r.bottom


def click(hwnd, cx, cy):
    """클라이언트 좌표 클릭 (PostMessage, 포커스 불필요)."""
    lp = (cy << 16) | (cx & 0xFFFF)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, 1, lp)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lp)


def key(hwnd, vk):
    lp_down = 1
    lp_up = 0xC0000001
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk, lp_down)
    user32.PostMessageW(hwnd, WM_KEYUP, vk, lp_up)
