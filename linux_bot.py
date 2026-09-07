"""로그인된 Linux 퍼플온 창을 사용하는 사냥 제어기. 기본 실행은 관찰 모드."""

import argparse
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import time

import cv2
import numpy as np

from linux_vision import analyze, find_character, motion_blobs, validate_target_profiles
from linux_window import PurpleWindow


RUNTIME = Path("/tmp/linc-bot-linux")
STOP_PATH = RUNTIME / "stop"
STATUS_PATH = RUNTIME / "status.json"
LOCK_PATH = RUNTIME / "controller.lock"


def write_status(**state):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    staging = STATUS_PATH.with_suffix(".pending")
    staging.write_text(json.dumps({"time": time.time(), "pid": os.getpid(), **state},
                                 ensure_ascii=False), encoding="utf-8")
    staging.replace(STATUS_PATH)


def choose_action(state, *, running, potion_key=None):
    """확인되지 않은 HUD, 마을, 저체력에서는 공격하지 않는다."""
    if not running or not state["ready"]:
        return None
    hp = state["hp"]
    if hp is None or hp <= 0:
        return None
    if hp < 0.55:
        return ("물약", potion_key) if potion_key else None
    if state["safe_zone"] or not state["mobs"]:
        return None
    target = min(state["mobs"], key=lambda m: (m[0] - 1220) ** 2 + (m[1] - 580) ** 2)
    return "공격", target[:2]


def choose_move_or_potion(state, move, potion_key=None):
    """이동 전용 모드에서도 저체력이면 이동보다 물약을 우선한다."""
    hp = state["hp"]
    if potion_key and hp is not None and 0 < hp < 0.55:
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
    state = {"reason": "사냥 시작", "hp": None, "mp": None, "ready": False,
             "game_visible": False, "safe_zone": False, "mobs": [], "candidates": []}
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            if window.stop_pressed() or stop_path.exists():
                logging.info("중지 요청으로 사냥 종료")
                break
            if not window.active():
                state["reason"] = "퍼플온 창이 비활성 상태"
                write_status(running=True, input_enabled=False, hunting=True, kills=kills, **state)
                wait_or_stop(window, args.interval, stop_path)
                continue
            frame = stable_frame(window, stop_path)
            if frame is None:
                break
            geometry = window.geometry()
            state = analyze(frame, target_profiles={})
            state["mobs"] = []
            write_status(running=True, input_enabled=True, hunting=True, kills=kills, **state)
            logging.info("HP=%s 마을=%s 사냥=%s/%s %s", state["hp"], state["safe_zone"],
                         kills, args.walk, state["reason"])
            hp = state["hp"]
            if hp is None or hp <= 0:
                logging.info("HP 판독 불가/사망: 대기")
                wait_or_stop(window, args.interval, stop_path)
                continue
            if hp < 0.55 and args.potion_key:
                window.key(args.potion_key, geometry)
                logging.info("물약 %s", args.potion_key)
                time.sleep(1.0)
                continue
            if state["safe_zone"]:
                logging.info("마을 안전 구역: 배회 이동")
                char = find_character(frame)
                base = char[:2] if char else (1150, 650)
                window.click(max(600, min(base[0] + 160, 1290)),
                             max(250, min(base[1] + 40, 730)), geometry)
                wait_or_stop(window, args.interval, stop_path)
                continue
            # 차분 몹 탐지: 안정 프레임과 1초 후 프레임 비교
            char = find_character(frame)
            time.sleep(1.0)
            if window.stop_pressed() or stop_path.exists() or not window.active():
                continue
            later = window.capture()
            if window.geometry() != geometry:
                continue
            blobs, _ = motion_blobs(later, frame, char[:2] if char else None)
            state["candidates"] = blobs
            if not blobs:
                if last_target:
                    logging.info("전투 종료 추정: 드랍 루팅 %s", last_target)
                    for dx, dy in ((0, 0), (35, 30), (-35, 30)):
                        window.click(max(560, min(last_target[0] + dx, 1290)),
                                     max(240, min(last_target[1] + dy, 730)), geometry)
                        time.sleep(0.8)
                    last_target = None
                else:
                    logging.info("몹 없음: 배회 이동")
                    char_now = find_character(later)
                    base = char_now[:2] if char_now else (1150, 650)
                    window.click(max(600, min(base[0] + 160, 1290)),
                                 max(250, min(base[1] + 40, 730)), geometry)
                wait_or_stop(window, args.interval, stop_path)
                continue
            target = max(blobs, key=lambda b: b[2])
            last_target = target[:2]
            kills += 1
            logging.info("몹 공격 #%s: (%s,%s) 면적=%s 후보=%s", kills, target[0], target[1],
                         target[2], len(blobs))
            window.click(target[0], target[1], geometry, hover=0.75)
            save_frame(args.output / "hunt-last.png", later)
            time.sleep(4.5)
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
