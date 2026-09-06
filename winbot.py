"""리니지 클래식 자동사냥 봇 (네이티브 클라이언트, 세션2 administrator로 실행)

전략:
- 캐릭터: 화면에서 가장 밝은 블롭(광원) 중심
- HP/MP: 캐릭터 머리 위 오버헤드 바 (빨강=HP, 파랑=MP) 픽셀 비율
- 몬스터: 캐릭터 정지 상태에서 프레임 차분 → 움직이는 블롭 = 몹 후보 → 클릭 공격
- NPC 보호: 움직이지 않는 블롭은 클릭하지 않음 (상점 열림 사고 방지)
- 대화상자 안전장치: 밝은 UI 패널 감지 시 Cancel 위치 클릭
- 정체(안티스턱): 일정 시간 활동 없으면 랜덤 방향 클릭 이동

중지: C:\\Users\\moony\\linc-bot\\stop.txt 파일 생성하면 루프 종료
"""
import ctypes
import ctypes.wintypes as wt
import json
import math
import os
import random
import sys
import time

sys.path.insert(0, r"C:\Users\moony\linc-bot")
import cv2
import numpy as np

from wincap import BITMAPINFOHEADER, client_size, find_window, grab_window

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
BASE = r"C:\Users\moony\linc-bot"
OUT = os.path.join(BASE, "debug")
STOP = os.path.join(BASE, "stop.txt")
LOG = os.path.join(BASE, "winbot.log")

CFG = json.load(open(os.path.join(BASE, "winbot-config.json"), encoding="utf-8"))
SCEN = json.load(open(os.path.join(BASE, "scenario.json"), encoding="utf-8"))

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("mi", MOUSEINPUT)]


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("cp949", "replace").decode("cp949"), flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def mouse_abs(x, y, flags):
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    extra = wt.ULONG(0)
    inp = INPUT(type=0, mi=MOUSEINPUT(int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1)),
                                      0, flags | MOUSEEVENTF_ABSOLUTE, 0, ctypes.pointer(extra)))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    _mark_bot_input()


def _mark_bot_input():
    global BOT_TICK
    BOT_TICK = ctypes.windll.kernel32.GetTickCount()


BOT_TICK = 0


def screen_click(sx, sy):
    mouse_abs(sx, sy, MOUSEEVENTF_MOVE)
    time.sleep(random.uniform(0.05, 0.12))
    mouse_abs(sx, sy, MOUSEEVENTF_LEFTDOWN)
    time.sleep(random.uniform(0.03, 0.08))
    mouse_abs(sx, sy, MOUSEEVENTF_LEFTUP)


def send_key(vk):
    extra = wt.ULONG(0)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                    ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]

    class KINPUT(ctypes.Structure):
        _fields_ = [("type", wt.DWORD), ("ki", KEYBDINPUT)]

    for fl in (0, 2):  # down, up(KEYEVENTF_KEYUP)
        inp = KINPUT(type=1, ki=KEYBDINPUT(vk, 0, fl, 0, ctypes.pointer(extra)))
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        time.sleep(0.03)
    _mark_bot_input()


def game_click(hwnd, rect, ix, iy):
    """게임 창을 포그라운드로 올린 뒤 이미지(윈도우) 좌표로 실클릭."""
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    screen_click(rect[0] + ix, rect[1] + iy)


def grab(hwnd, rect):
    """화면 BitBlt (포그라운드 상태 전제). BGR 이미지."""
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
    return np.frombuffer(buf, np.uint8).reshape(h, w, 4)[:, :, :3].copy()


def find_char(img, last_pos=None, char_below=45):
    """오버헤드 HP 바로 캐릭터 탐지 → (cx, cy, hp). 없으면 (None,None,-1).

    실측: 바 = 빨강(HP 채움)+청백 트랙, HSV red(sat150+,val120+)|blue(h95-130)
    마스크 + 가로 close → 25~100px 가로형 컨투어가 바 하나만 남음.
    아래 15~95px 영역 평균밝기 ≥22 (캐릭터 광원) 조건으로 오탐 제거.
    HP = 바 안 BGR 기준 R>B+10 & R>18 열 비율 (어두운 빨강 포함).
    """
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, (0, 150, 120), (10, 255, 255)) | \
          cv2.inRange(hsv, (170, 150, 120), (180, 255, 255))
    blue = cv2.inRange(hsv, (95, 120, 100), (130, 255, 255))
    mask = red | blue
    mask[:int(h * 0.12), :] = 0
    mask[int(h * 0.92):, :] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 25), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in cnts:
        x, y, bw, bh = cv2.boundingRect(c)
        if not (25 <= bw <= 100 and 3 <= bh <= 14):
            continue
        below = img[y + bh + 15:y + bh + 95, max(0, x - 25):x + bw + 25]
        below_mean = below.mean() if below.size else 0
        if below_mean < 22:
            continue
        bgr = img[y:y + bh, x:x + bw].astype(np.int16)
        rr, bb = bgr[:, :, 2], bgr[:, :, 0]
        red_cols = ((rr > bb + 10) & (rr > 18)).any(axis=0)
        hp = float(red_cols.sum()) / bw
        cx, cy = x + bw // 2, y + bh + char_below
        score = below_mean + bw * 0.5
        if last_pos:
            score -= math.hypot(cx - last_pos[0], cy - last_pos[1]) * 0.3
        if best is None or score > best[0]:
            best = (score, cx, cy, hp)
    if best is None:
        return None, None, -1.0
    return best[1], best[2], best[3]


def motion_blobs(img, prev, cx, cy):
    """프레임 차분으로 움직이는 블롭 (캐릭터 주변 제외)."""
    diff = cv2.absdiff(img, prev)
    gray = diff.max(axis=2).astype(np.uint8)
    _, th = cv2.threshold(gray, CFG["motion_threshold"], 255, cv2.THRESH_BINARY)
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    th = cv2.dilate(th, np.ones((5, 5), np.uint8))
    change_ratio = float((th > 0).mean())
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    blobs = []
    for c in cnts:
        a = cv2.contourArea(c)
        if CFG["mob_min_area"] <= a <= CFG["mob_max_area"]:
            m = cv2.moments(c)
            if m["m00"]:
                bx, by = int(m["m10"] / m["m00"]), int(m["m01"] / m["m00"])
                if math.hypot(bx - cx, by - cy) > CFG["char_exclude_radius"]:
                    blobs.append((bx, by, int(a)))
    return blobs, change_ratio


def last_input_tick():
    """GetLastInputInfo dwTime (틱 카운트 ms)."""
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]
    lii = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    user32.GetLastInputInfo(ctypes.byref(lii))
    return lii.dwTime


def screen_grab(rect):
    """화면 BitBlt (UI 오버레이 포함 — 인벤/상점 캡처용)."""
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
    return np.frombuffer(buf, np.uint8).reshape(h, w, 4)[:, :, :3].copy()


def read_weight_pct(hwnd, rect):
    """인벤토리(Tab) 열어 무게 게이지 판독 → %. 미캘리브레이션이면 None.

    weight_bar_rect = [x, y, w, h] (윈도우 기준). 게이지 채움 비율로 환산.
    """
    if not SCEN.get("weight_bar_rect"):
        return None
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    send_key(SCEN["inventory_open_key"])  # Tab
    time.sleep(1.2)
    img = screen_grab(rect)
    cv2.imwrite(os.path.join(OUT, f"inv_{int(time.time())}.jpg"), img,
                [cv2.IMWRITE_JPEG_QUALITY, 85])
    send_key(SCEN["inventory_open_key"])  # Tab 닫기
    x, y, w, h = SCEN["weight_bar_rect"]
    bar = img[y:y + h, x:x + w]
    if bar.size == 0:
        return None
    # 게이지 채움: 배경 대비 밝은(채워진) 열 비율 — 실측 후 임계 조정
    gray = cv2.cvtColor(bar, cv2.COLOR_BGR2GRAY)
    filled = (gray > gray.mean() + 25).mean(axis=0)
    cols = (filled > 0.5).sum()
    return cols / max(1, w) * 100.0


def run_waypoints(hwnd, rect, waypoints, tag):
    """[x, y, delay_sec] 시퀀스 클릭 (윈도우 기준 좌표)."""
    for i, wp in enumerate(waypoints):
        wx, wy, delay = wp
        log(f"{tag} 웨이포인트 {i + 1}/{len(waypoints)} ({wx},{wy})")
        game_click(hwnd, rect, wx, wy)
        time.sleep(delay)


def sell_routine(hwnd, rect):
    """마을 귀환 → 상인 이동 → 판매 → 보충 → 복귀 (scenario.json 기반)."""
    tr = SCEN["town_return"]
    if not tr.get("key"):
        log("귀환 수단 미설정 → 판매 루틴 스킵")
        return
    log("=== 판매 루틴 시작 ===")
    send_key(tr["key"])
    time.sleep(tr["arrive_wait_sec"])
    if SCEN["shop_waypoints"]:
        run_waypoints(hwnd, rect, SCEN["shop_waypoints"], "상인이동")
    if SCEN["shopkeeper_click"]:
        sx, sy = SCEN["shopkeeper_click"]
        game_click(hwnd, rect, sx, sy)
        time.sleep(2)
    for step in SCEN["shop_sell_flow"]:
        run_waypoints(hwnd, rect, [step], "판매")
    for step in SCEN["potion_buy_flow"]:
        run_waypoints(hwnd, rect, [step], "보충")
    if SCEN["return_waypoints"]:
        run_waypoints(hwnd, rect, SCEN["return_waypoints"], "사냥터복귀")
    log("=== 판매 루틴 완료 ===")


def main():
    log("봇 시작 - 게임 창 대기 모드")
    hwnd, rect = find_window("Lineage Classic")
    while not hwnd and not os.path.exists(STOP):
        hwnd, rect = find_window("Lineage Classic")
        time.sleep(5)
    if hwnd:
        log(f"게임 창 발견 hwnd={hwnd} rect={rect}")

    prev = None
    last_action = time.time()
    last_debug = 0.0
    last_potion = 0.0
    moving_since = None
    last_char = None
    low_streak = 0
    last_target = None
    combat_idle = 0
    last_inv_check = time.time()

    while not os.path.exists(STOP):
        hwnd, rect = find_window("Lineage Classic")  # 이동/리사이즈 추적
        if not hwnd:
            log("게임 창 소실 → 대기")
            time.sleep(3)
            prev = None
            continue
        # 사용자 활동 양보: 내 SendInput 이후 2.5초 이상 지난 외부 입력만 사용자로 간주
        tick = ctypes.windll.kernel32.GetTickCount()
        li = last_input_tick()
        if (li - BOT_TICK) > 2500 and (tick - li) < CFG["user_yield_sec"] * 1000:
            if prev is not None or moving_since is not None:
                log("사용자 입력 감지 → 사냥 일시정지")
            prev = None
            moving_since = None
            time.sleep(5)
            continue
        img0 = grab_window(hwnd, rect)  # PrintWindow 우선 (가려져도 캡처)
        # 소창 대응: 폭 700px 미만이면 2배 업스케일 후 분석 (좌표는 클릭 시 환원)
        scale = 2.0 if img0.shape[1] < 700 else 1.0
        if scale != 1.0:
            img = cv2.resize(img0, None, fx=scale, fy=scale,
                             interpolation=cv2.INTER_CUBIC)
        else:
            img = img0
        h, w = img.shape[:2]
        last_char_s = (int(last_char[0] * scale), int(last_char[1] * scale)) \
            if last_char else None
        cx, cy, hp = find_char(img, last_char_s, int(45 * scale))
        if cx is None:
            log("캐릭터 미탐지 (로딩/사망?) 대기")
            prev = None
            time.sleep(2)
            continue
        last_char = (cx / scale, cy / scale)

        # (대화상자/HUD는 PrintWindow 캡처에 포함되지 않으므로 별도 처리 불필요)

        # 포션 (2회 연속 저HP 판독 시에만 — 오판 방지)
        now = time.time()
        low_hp = 0 <= hp < CFG["hp_potion_threshold"]
        low_streak = low_streak + 1 if low_hp else 0
        if low_streak >= 2 and now - last_potion > CFG["potion_cooldown"]:
            log(f"HP {hp:.0%} → 포션 키 {CFG['potion_key']:#x}")
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.1)
            send_key(CFG["potion_key"])
            last_potion = now

        # 주기적 인벤토리 무게 체크 → 판매 시나리오
        if now - last_inv_check > SCEN["inv_check_interval_sec"]:
            last_inv_check = now
            wpct = read_weight_pct(hwnd, rect)
            if wpct is not None:
                log(f"인벤 무게 {wpct:.0f}%")
                if wpct >= SCEN["inv_weight_threshold_pct"]:
                    sell_routine(hwnd, rect)
                    prev = None
                    moving_since = None
                    last_target = None
                    continue

        # 이동 중이면 정착 대기
        if prev is not None:
            blobs, change_ratio = motion_blobs(img, prev, cx, cy)
            if moving_since is not None:
                if change_ratio > CFG["scroll_threshold"]:
                    if time.time() - moving_since > CFG["max_travel_sec"]:
                        log("이동 타임아웃 → 재시도")
                        moving_since = None
                    prev = img
                    time.sleep(0.5)
                    continue
                moving_since = None  # 정착됨

            if blobs:
                bx, by, area = min(blobs, key=lambda b: math.hypot(b[0] - cx, b[1] - cy))
                log(f"몹 클릭 ({bx},{by}) area={area} HP={hp:.0%}")
                game_click(hwnd, rect, int(bx / scale) + random.randint(-3, 3),
                           int(by / scale) + random.randint(-3, 3))
                last_target = (int(bx / scale), int(by / scale))
                combat_idle = 0
                last_action = now
                moving_since = now
                prev = None
                time.sleep(random.uniform(1.0, 1.8))
                continue

            # 전투 종료 판정: 타겟 잡은 뒤 움직이는 블롭 소멸 → 루팅
            if last_target is not None:
                combat_idle += 1
                if combat_idle >= 2:
                    log(f"킬 완료 → 루팅 (F4 토글) at {last_target}")
                    user32.ShowWindow(hwnd, 9)
                    user32.SetForegroundWindow(hwnd)
                    time.sleep(0.1)
                    send_key(0x73)  # F4 줍기 모드 ON
                    time.sleep(random.uniform(0.2, 0.4))
                    for ddx, ddy in ((0, 0), (12, 8), (-12, -6)):
                        game_click(hwnd, rect,
                                   last_target[0] + ddx, last_target[1] + ddy)
                        time.sleep(random.uniform(0.3, 0.6))
                    send_key(0x73)  # F4 줍기 모드 OFF
                    log("루팅 완료 (F4 OFF)")
                    last_target = None
                    combat_idle = 0
                    last_action = time.time()
                    prev = None
                    time.sleep(0.8)
                    continue

        # 배회
        if time.time() - last_action > CFG["wander_idle_sec"]:
            ang = random.uniform(0, 2 * math.pi)
            rad = random.uniform(0.2, 0.35)
            wx = int(cx + w * rad * math.cos(ang) * 0.5)
            wy = int(cy + h * rad * math.sin(ang) * 0.5)
            wx = max(int(w * 0.12), min(int(w * 0.88), wx))
            wy = max(int(h * 0.18), min(int(h * 0.85), wy))
            log(f"배회 클릭 ({wx},{wy})")
            game_click(hwnd, rect, int(wx / scale), int(wy / scale))
            last_action = time.time()
            moving_since = time.time()
            prev = None
            time.sleep(1.0)
            continue

        # 디버그 스냅샷
        if now - last_debug > 15:
            dbg = img.copy()
            cv2.circle(dbg, (cx, cy), 10, (0, 255, 255), 2)
            if prev is not None:
                blobs2, _ = motion_blobs(img, prev, cx, cy)
                for bx, by, a in blobs2:
                    cv2.circle(dbg, (bx, by), 8, (0, 0, 255), 2)
            cv2.putText(dbg, f"HP={hp:.2f}", (10, h - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.imwrite(os.path.join(OUT, f"winbot_{int(now)}.jpg"), dbg,
                        [cv2.IMWRITE_JPEG_QUALITY, 80])
            # 오래된 디버그 스냅샷 정리 (최신 10장 유지)
            shots = sorted(f for f in os.listdir(OUT) if f.startswith("winbot_"))
            for f in shots[:-10]:
                try:
                    os.remove(os.path.join(OUT, f))
                except OSError:
                    pass
            last_debug = now

        prev = img
        time.sleep(random.uniform(0.5, 0.9))

    log("stop.txt 감지 → 종료")
    try:
        os.remove(STOP)
    except OSError:
        pass


if __name__ == "__main__":
    main()
