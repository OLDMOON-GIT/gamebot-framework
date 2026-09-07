"""로그인된 Linux 퍼플온 창을 사용하는 사냥 제어기. 기본 실행은 관찰 모드."""

import argparse
import math
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import time

import cv2
import numpy as np

from linux_vision import (analyze, detect_mobs, find_character, scan_drops,
                          forbidden_mob_check, mark_template_result, mob_hp_bars,
                          motion_blobs, save_mob_template, validate_target_profiles)
from linux_window import PurpleWindow


POTION_THRESHOLD = 0.70  # 사용자 지정(2026-09-07): 70%에서 물약
MAX_MOB_CANDIDATES = 200  # 이 초과는 잔상 폭증(배회 직후 실측 1000+)
SAFE_MOB_AREA = 3000     # 이 면적 초과 블롭은 돌골렘급 거대 몹으로 보고 공격 안 함
RUNTIME = Path("/tmp/linc-bot-linux")
STOP_PATH = RUNTIME / "stop"
STATUS_PATH = RUNTIME / "status.json"
LOCK_PATH = RUNTIME / "controller.lock"


def write_status(**state):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    staging = STATUS_PATH.with_suffix(".pending")
    staging.write_text(json.dumps({"time": time.time(), "pid": os.getpid(), **state}, default=str,
                                 ensure_ascii=False), encoding="utf-8")
    staging.replace(STATUS_PATH)


def choose_action(state, *, running, potion_key=None):
    """확인되지 않은 HUD, 마을, 저체력에서는 공격하지 않는다."""
    if not running or not state["ready"]:
        return None
    hp = state["hp"]
    if hp is None or hp <= 0:
        return None
    if hp < POTION_THRESHOLD:
        return ("물약", potion_key) if potion_key else None
    if state["safe_zone"] or not state["mobs"]:
        return None
    target = min(state["mobs"], key=lambda m: (m[0] - 1220) ** 2 + (m[1] - 580) ** 2)
    return "공격", target[:2]


def choose_move_or_potion(state, move, potion_key=None):
    """이동 전용 모드에서도 저체력이면 이동보다 물약을 우선한다."""
    hp = state["hp"]
    if potion_key and hp is not None and 0 < hp < POTION_THRESHOLD:
        return ("물약", potion_key)
    return ("이동", move)


def stable_frame(window, stop_path, timeout=8.0, region=(520, 220, 780, 530)):
    """화면 변경이 잦아지지 않을 때까지 기다렸다가 안정 프레임을 돌려준다."""
    prev = window.capture()
    deadline = time.monotonic() + timeout
    while True:
        if window.stop_pressed() or stop_path.exists():
            return None
        if time.monotonic() >= deadline:
            return prev
        time.sleep(0.7)
        current = window.capture()
        left, top, width, height = region
        diff = cv2.absdiff(prev[top:top + height, left:left + width],
                           current[top:top + height, left:left + width])
        ratio = np.count_nonzero(diff.max(axis=2) > 30) / (width * height)
        if ratio < 0.005:
            return current
        prev = current


def hunt_loop(window, stop_path, args):
    """실측 검증 사이클: 정지→차분 몹 탐지→hover 공격→처치 대기→루팅→배회.

    몹 이름표가 평소 표시되지 않는 리니지 클래식 특성상 이름 프로필 대신
    프레임 차분(움직이는 블롭)으로 몹을 찾는다. hover 0.7초 이상 클릭이
    이동이 아닌 공격으로 해석되는 것까지 2026-09-07 실물 검증 완료.
    """
    kills = 0
    last_target = None
    stale = 0  # 몹 없음 연속 횟수 — 방향 순환용
    prev_hp = None  # 전투 중 판정: HP가 하락하면 자동전투가 돌고 있는 것이다
    loot_blacklist = set()  # 클릭해도 안 줍히는 좌표(바닥 오탐)
    state = {"reason": "사냥 시작", "hp": None, "mp": None, "ready": False,
             "game_visible": False, "safe_zone": False, "mobs": [], "candidates": []}
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            if window.stop_pressed() or stop_path.exists():
                logging.info("중지 요청으로 사냥 종료")
                break
            if not window.active():
                try:
                    window.find_and_restore()
                    logging.info("퍼플온 창 복구: %s", hex(window.window_id))
                except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                    state["reason"] = f"퍼플온 창 복구 실패 대기: {exc}"
                    write_status(running=True, input_enabled=False, hunting=True,
                                 kills=kills, **state)
                    wait_or_stop(window, args.interval, stop_path)
                    continue
            try:
                frame = stable_frame(window, stop_path)
            except (RuntimeError, OSError) as exc:
                logging.info("캡처 실패로 창 복구 시도: %s", exc)
                try:
                    window.find_and_restore()
                except (RuntimeError, OSError, subprocess.SubprocessError):
                    pass
                continue
            if frame is None:
                break
            geometry = window.geometry()
            state = analyze(frame, target_profiles={}, require_url=not args.cdp)
            if state["reason"] == "화면 크기 불일치":
                logging.info("화면 크기 불일치로 창 복구 시도")
                try:
                    window.find_and_restore()
                except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                    logging.info("창 복구 실패: %s", exc)
                continue
            state["mobs"] = []
            write_status(running=True, input_enabled=True, hunting=True, kills=kills, **state)
            logging.info("HP=%s 마을=%s 사냥=%s/%s %s", state["hp"], state["safe_zone"],
                         kills, args.walk, state["reason"])
            hp = state["hp"]
            if hp is None:
                # CDP 창은 HUD 텍스트 슬래시가 OCR에 잘 안 걸린다(실측).
                # 캐릭터 머리 위 HP 막대 비율로 대체 판독한다(오차 -0.05 보정).
                bar = find_character(frame)
                if bar and bar[2] > 0.05:  # 0.0은 다른 플레이어 막대 오탐
                    hp = max(0.0, bar[2] - 0.05)
                    state["hp"] = hp
                    state["game_visible"] = True
                    logging.info("HP 막대 폴백 판독: %.2f", hp)
            if hp is None or hp <= 0:
                logging.info("HP 판독 불가/사망: 대기")
                wait_or_stop(window, args.interval, stop_path)
                continue
            if hp < POTION_THRESHOLD and args.potion_key:
                # CDP dispatchKeyEvent가 게임에 안 통한다(실측: HP 0.5대
                # 연타 무효). 퀵슬롯 첫 아이콘(물약, 실측 1590,1255) 클릭.
                window.click(1590, 1255, geometry)
                logging.info("물약 클릭(퀵슬롯)")
                time.sleep(1.2)
                continue
            if prev_hp is not None and hp < prev_hp - 0.02:
                # HP가 하락 중 = 몹이 붙어서 자동전투 중(실측: 붙은 몹은
                # 캐릭터 제외 반경에 가려 탐지도 안 된다). 개입하지 않는다.
                logging.info("자동전투 진행 중(HP %.2f→%.2f): 대기", prev_hp, hp)
                prev_hp = hp
                stale = 0
                time.sleep(2.5)
                continue
            prev_hp = hp
            if state["safe_zone"]:
                # 마을 탈출 실측 경로: 서쪽 (580,700) 클릭 반복이 하이네에서
                # 필드(Normal zone)로 빠져나가는 유일하게 검증된 방향이다.
                logging.info("마을 안전 구역: 서쪽 탈출 이동")
                window.click(580, 700, geometry)
                wait_or_stop(window, args.interval, stop_path)
                continue
            # 몹 탐지 1순위: 템플릿 매칭(정지 몹도 즉시 포착)
            template_mobs = detect_mobs(frame)
            if template_mobs:
                char = find_character(frame)
                near = [m for m in template_mobs
                        if not (char and math.hypot(m[0]-char[0], m[1]-char[1]) <= 90)]
                if near:
                    tx, ty, tname = near[0]
                    kills += 1
                    last_target = (tx, ty)
                    logging.info("템플릿 몹 공격 #%s: (%s,%s) %s", kills, tx, ty, tname)
                    window.click(tx, ty, geometry, hover=0.75)
                    time.sleep(6.0)
                    try:
                        after = window.capture()
                    except (RuntimeError, OSError):
                        continue
                    # 6초 뒤에도 같은 템플릿이 같은 자리에 있으면 배경이다.
                    rematch = [m for m in detect_mobs(after)
                               if m[2] == tname and abs(m[0]-tx) <= 40 and abs(m[1]-ty) <= 40]
                    if rematch:
                        removed = mark_template_result(tname, killed=False)
                        logging.info("템플릿 %s 배경 판정%s", tname, " → 삭제" if removed else "")
                    else:
                        mark_template_result(tname, killed=True)
                        kills += 1  # 실제 처치로 확정
                        logging.info("템플릿 %s 처치 확정", tname)
                    continue
            # 몹 탐지 2순위: 차분(움직이는 몹)
            char = find_character(frame)
            time.sleep(1.0)
            if window.stop_pressed() or stop_path.exists() or not window.active():
                continue
            later = window.capture()
            if window.geometry() != geometry:
                continue
            blobs, _ = motion_blobs(later, frame, char[:2] if char else None)
            state["candidates"] = blobs
            if len(blobs) > MAX_MOB_CANDIDATES:
                # 배회 이동 직후 잔상이 폭증한다(실측 1000+). 잔상은 작은
                # 블롭이므로 큰 덩어리(500+)만 실몹 후보로 공격하고, 없으면
                # 제자리에서 잔상 소멸을 기다린다(이동 금지 — 잔상 재발).
                solid = [b for b in blobs if 500 <= b[2] <= SAFE_MOB_AREA]
                if solid:
                    logging.info("후보 과다(%s개) 중 대형 몹 공격: %s",
                                 len(blobs), max(solid, key=lambda b: b[2])[:2])
                    blobs = solid
                else:
                    logging.info("후보 과다(%s개): 제자리 대기(잔상 소멸)", len(blobs))
                    state["candidates"] = []
                    time.sleep(1.2)
                    continue
            if not blobs:
                # 화면의 밝은 드랍 군집을 직접 찾아 줍는다(클릭→사라짐 검증).
                drops = [d for d in scan_drops(later)
                         if (d[0], d[1]) not in loot_blacklist]
                if drops:
                    before_drops = {(d[0] // 20, d[1] // 20) for d in drops}
                    for dx_, dy_, _ in drops[:3]:
                        window.click(max(560, min(dx_, 1290)),
                                     max(240, min(dy_, 730)), geometry)
                        time.sleep(1.2)
                    try:
                        after_drops = {(d[0] // 20, d[1] // 20)
                                       for d in scan_drops(window.capture())}
                    except (RuntimeError, OSError):
                        after_drops = before_drops
                    picked = before_drops - after_drops
                    for d in drops[:3]:
                        if (d[0] // 20, d[1] // 20) not in picked:
                            loot_blacklist.add((d[0], d[1]))
                    if picked:
                        logging.info("드랍 줍기 성공 %s개", len(picked))
                    continue
                else:
                    stale += 1
                    # 우측 고정 배회는 몹 없는 지역으로 무한 직진한다(실측).
                    # 몹 없음이 이어지면 방향을 순환해 사냥터를 탐색한다.
                    directions = ((160, 40), (-160, 40), (-160, -40), (160, -40))
                    dx, dy = directions[stale % len(directions)]
                    char_now = find_character(later)
                    base = char_now[:2] if char_now else (1150, 650)
                    logging.info("몹 없음(%s회): 배회 %s", stale, (dx, dy))
                    window.click(max(600, min(base[0] + dx, 1290)),
                                 max(250, min(base[1] + dy, 730)), geometry)
                wait_or_stop(window, args.interval, stop_path)
                continue
            safe_blobs = [b for b in blobs if b[2] <= SAFE_MOB_AREA]
            if not safe_blobs:
                logging.info("후보 전체가 거대 몹(면적>%s): 공격 보류", SAFE_MOB_AREA)
                wait_or_stop(window, args.interval, stop_path)
                continue
            stale = 0  # 몹 발견: 배회 방향 리셋
            target = max(safe_blobs, key=lambda b: b[2])
            last_target = target[:2]
            kills += 1
            logging.info("몹 공격 #%s: (%s,%s) 면적=%s 후보=%s", kills, target[0], target[1],
                         target[2], len(blobs))
            window.click(target[0], target[1], geometry, hover=0.75)
            saved = save_mob_template(later, target[0], target[1])
            if saved:
                logging.info("몹 템플릿 적립: %s", saved)
            save_frame(args.output / "hunt-last.png", later)
            # 전투 종료까지 대기: 몹 HP 막대(노란 게이지)가 사라지면 처치 완료.
            # 금지 몹(돌골렘 등)이 타겟에 걸리면 즉시 이탈한다(2026-09-07 지시).
            combat_deadline = time.monotonic() + 8
            while time.monotonic() < combat_deadline:
                if window.stop_pressed() or stop_path.exists() or not window.active():
                    break
                time.sleep(1.5)
                try:
                    combat_frame = window.capture()
                except (RuntimeError, OSError):
                    break
                forbidden, why = forbidden_mob_check(combat_frame)
                if forbidden:
                    logging.info("금지 몹 감지(%s): 즉시 이탈", why)
                    window.click(1000, 300, geometry)
                    last_target = None
                    break
                if mob_hp_bars(combat_frame):
                    continue  # 몹 HP 막대가 남아 있으면 전투 지속
                break
            logging.info("전투 대기 종료 (몹 HP 막대 소멸/시간초과)")
            if kills >= args.walk:
                logging.info("공격 상한 %s 도달: 사냥 종료", args.walk)
                break
    finally:
        write_status(running=False, input_enabled=False, hunting=True, kills=kills, **state)
        logging.info("사냥 모드 종료, 처치 %s", kills)


def save_frame(path, frame):
    if not cv2.imwrite(str(path), frame):
        raise RuntimeError(f"스크린샷 저장 실패: {path}")


def input_unchanged(window, original_pointer, stop_path):
    """OCR 전후 사용자가 입력했거나 종료를 요청했다면 해당 프레임을 버린다."""
    return (not window.stop_pressed() and not stop_path.exists()
            and window.pointer() == original_pointer)


def wait_or_stop(window, seconds, stop_path):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if window.stop_pressed() or stop_path.exists():
            return
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        "관찰: python3 linux_bot.py --seconds 30 | "
        "사냥: python3 linux_bot.py --run --targets 확인한몹.json --seconds 300 | "
        "중지: python3 linux_bot.py --stop | 상태: python3 linux_bot.py --status. "
        "몹 JSON 형식은 {몬스터이름: [이름표에서 몸체까지의 x차이, y차이]}입니다. "
        "현재 기본 캘리브레이션은 1933x1332 창 전용입니다."))
    control = parser.add_mutually_exclusive_group()
    control.add_argument("--stop", action="store_true", help="실행 중 제어기에 중지 요청")
    control.add_argument("--status", action="store_true", help="마지막 판독과 실제 실행 여부 표시")
    parser.add_argument("--run", action="store_true", help="실제 공격 입력 허용")
    parser.add_argument("--targets", type=Path, help="실물에서 확인한 몬스터 이름/몸체 오프셋 JSON")
    parser.add_argument("--seconds", type=float, default=30, help="실행 시간, 기본 30초")
    parser.add_argument("--interval", type=float, default=1.5, help="프레임 확인 간격")
    parser.add_argument("--potion-key", choices=[f"F{i}" for i in range(1, 9)],
                        help="실제로 물약이 배치된 것으로 확인한 키만 지정")
    parser.add_argument("--window", type=lambda value: int(value, 0), help="X11 창 ID")
    parser.add_argument("--cdp", action="store_true",
                        help="CDP(원격 디버깅) 크롬으로 마우스/포커스 간섭 없이 사냥")
    parser.add_argument("--click", nargs=2, type=int, help="실화면에서 확인한 위치 한 번 클릭")
    parser.add_argument("--walk", type=int, default=1,
                        help="--click 위치를 지정 횟수만큼 interval 간격으로 반복 클릭")
    parser.add_argument("--hunt", action="store_true",
                        help="차분 몹 탐지+공격+루팅 자동 사냥 (--run 필요, walk=공격 상한)")
    parser.add_argument("--output", type=Path, default=Path("/tmp/linc-bot-linux"))
    args = parser.parse_args()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if args.stop:
        STOP_PATH.touch()
        print("중지 요청을 기록했습니다.")
        return
    if args.status:
        last = json.loads(STATUS_PATH.read_text(encoding="utf-8")) if STATUS_PATH.exists() else {}
        with LOCK_PATH.open("a") as check:
            try:
                fcntl.flock(check, fcntl.LOCK_EX | fcntl.LOCK_NB)
                last["running"] = False
            except BlockingIOError:
                last["running"] = True
        print(json.dumps(last, ensure_ascii=False, indent=2))
        return
    try:
        targets = validate_target_profiles(json.loads(args.targets.read_text(encoding="utf-8"))) \
            if args.targets else {}
    except (OSError, ValueError) as exc:
        parser.error(f"몬스터 프로필 오류: {exc}")
    if args.run and not args.click and not args.hunt and not targets:
        parser.error("실물 몬스터 프로필이 없어 사냥을 시작하지 않았습니다. --targets가 필요합니다.")
    if not 0 < args.seconds <= 3600 or not 0.5 <= args.interval <= 30:
        parser.error("실행 시간은 0초 초과~3600초, 간격은 0.5~30초여야 합니다")
    if args.click and not args.run:
        parser.error("위치 클릭은 --run과 함께 지정해야 합니다")
    if not args.click and not args.hunt and args.walk != 1:
        parser.error("--walk는 --click과 함께 지정해야 합니다")
    if args.walk < 1 or args.walk > 200:
        parser.error("반복 클릭 횟수는 1~200이어야 합니다")
    if args.hunt:
        if not args.run:
            parser.error("사냥 모드는 --run과 함께 지정해야 합니다")
        if args.click:
            parser.error("--hunt와 --click은 동시에 지정할 수 없습니다")
        if args.walk < 1 or args.walk > 200:
            parser.error("사냥 공격 상한은 1~200이어야 합니다")
        if args.walk == 1:
            args.walk = 50  # 사냥 모드 공격 상한 기본값
    args.output.mkdir(parents=True, exist_ok=True)
    # 출력 폴더를 바꿔도 실제 입력 루프는 한 개만 실행한다.
    with LOCK_PATH.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("이미 Linux 퍼플온 제어기가 실행 중입니다")
        STOP_PATH.unlink(missing_ok=True)
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                            handlers=[logging.StreamHandler(),
                                      RotatingFileHandler(args.output / "run.log", encoding="utf-8",
                                                          maxBytes=1_000_000, backupCount=2)])
        if args.cdp:
            from cdp_window import CdpWindow
            window = CdpWindow()
            logging.info("CDP 백엔드 연결(마우스/포커스 무간섭)")
        else:
            window = PurpleWindow(args.window)
        deadline = time.monotonic() + args.seconds
        previous_pointer = window.pointer()
        user_pause_until = 0.0
        last_potion = 0.0
        index = 0
        state = {"reason": "시작 중"}
        try:
            if args.hunt:
                logging.info("창=%s 모드=사냥(차분) F12 또는 Ctrl+C로 종료",
                             hex(window.window_id))
                hunt_loop(window, STOP_PATH, args)
                return
            write_status(running=True, input_enabled=args.run, **state)
            logging.info("창=%s 모드=%s F12 또는 Ctrl+C로 종료", hex(window.window_id),
                         "실제 입력" if args.run else "관찰")
            while time.monotonic() < deadline:
                if window.stop_pressed() or STOP_PATH.exists():
                    logging.info("중지 요청으로 종료")
                    break
                if not window.active():
                    state = {"reason": "퍼플온 창이 비활성 상태", "ready": False}
                    write_status(running=True, input_enabled=False, **state)
                    logging.info("대기: 퍼플온 창이 비활성 상태")
                    if args.click:
                        raise RuntimeError("단발 클릭 취소: 퍼플온 창이 비활성 상태")
                    wait_or_stop(window, args.interval, STOP_PATH)
                    previous_pointer = window.pointer()
                    continue
                pointer = window.pointer()
                if pointer != previous_pointer:
                    user_pause_until = time.monotonic() + 3
                previous_pointer = pointer
                geometry = window.geometry()
                frame = window.capture()
                captured_at = time.monotonic()
                state = analyze(frame, target_profiles=targets)
                save_frame(args.output / "latest.png", frame)
                write_status(running=True, input_enabled=args.run,
                             window=hex(window.window_id), **state)
                logging.info("HP=%s MP=%s 마을=%s 몹=%s 판독=%s", state["hp"], state["mp"],
                             state["safe_zone"], len(state["mobs"]), state["reason"])
                if args.click:
                    if not state["game_visible"]:
                        raise RuntimeError("단발 클릭 취소: 게임 화면을 확인하지 못했습니다")
                    action = choose_move_or_potion(state, tuple(args.click), args.potion_key)
                else:
                    action = choose_action(state, running=args.run, potion_key=args.potion_key)
                if action and time.monotonic() >= user_pause_until:
                    if (time.monotonic() >= deadline
                            or time.monotonic() - captured_at > 2
                            or not input_unchanged(window, pointer, STOP_PATH)):
                        logging.info("판독 중 사용자 입력 또는 중지 요청: 이번 입력 취소")
                        previous_pointer = window.pointer()
                        user_pause_until = time.monotonic() + 3
                        if args.click:
                            break
                        continue
                    kind, payload = action
                    if kind == "물약" and time.monotonic() - last_potion < 2:
                        action = None
                    else:
                        save_frame(args.output / f"{index % 20:04d}-before.png", frame)
                        if time.monotonic() >= deadline or not input_unchanged(window, pointer, STOP_PATH):
                            break
                        if kind == "물약":
                            window.key(payload, geometry)
                            last_potion = time.monotonic()
                        else:
                            window.click(*payload, geometry)
                        previous_pointer = window.pointer()
                        logging.info("입력: %s %s", kind, payload)
                        time.sleep(0.6)
                        if window.active() and window.geometry() == geometry:
                            save_frame(args.output / f"{index % 20:04d}-after.png", window.capture())
                        index += 1
                        if args.click and index >= args.walk:
                            break
                wait_or_stop(window, args.interval, STOP_PATH)
        except KeyboardInterrupt:
            logging.info("Ctrl+C 요청으로 종료")
        finally:
            window.close()
            write_status(running=False, input_enabled=False, inputs=index, **state)
            logging.info("제어기 종료, 입력 %s회", index)


if __name__ == "__main__":
    main()
