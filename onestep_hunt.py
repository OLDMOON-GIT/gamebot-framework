"""한 칸 거리 사냥 — 캐릭터 주변 근접 몹만 잡는다(2026-09-09 사용자 지시).

이동하지 않는다. 캐릭터 근처(260px 이내)에서 움직이는 몹을 클릭해
자동전투로 잡고, HP 80% 미만이면 F5/F6 물약(potion_keys 공용 —
BTS-1033250로 종전 퀵슬롯 좌표 클릭은 폐지).
모든 터치 전 사용자 양보 게이트. 근접 몹 없으면 대기(배회 없음).
"""
import json
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from cdp_window import CdpWindow, EXT_PORT
from linux_vision import find_character, hp_read, red_name_candidates
from potion_keys import EXHAUSTED, USED, PotionKeys
from user_gate import user_active
from hunt_priority import RETURN, STOP, decide
from bot_settings import load as load_settings
from attack_skills import next_skill
from func_items import next_item

RUNTIME = Path("/tmp/linc-bot-linux")
STOP = RUNTIME / "stop"
NOMOUSE = RUNTIME / "nomouse"   # 마우스 클릭 전면 금지(사용자 지시 2026-09-15)
NEAR_RADIUS = 260            # 한 칸~두 칸: 캐릭터 중심 이 반경 몹만
EXT_HP_URL = "http://127.0.0.1:17311/hp"


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class UserBusy(Exception):
    """사용자가 계속 조작 중 — 이번 터치는 포기한다(강행 금지)."""


def yield_click(w, x, y, max_wait=120):
    """사용자 양보 후 클릭. 한도까지 기다려도 사용자가 손을 안 떼면 클릭하지
    않고 UserBusy 를 던진다(종전엔 120초 뒤 강행 → '또 마우스' 재발 경로)."""
    waited = 0
    while user_active() and not STOP.exists():
        if waited >= max_wait:
            raise UserBusy(f"사용자 조작 {waited}s 지속 — 터치 생략")
        time.sleep(2.0)
        waited += 2
    if STOP.exists():
        raise SystemExit
    w.click(x, y, w.geometry())


def near_named_mobs(cur, char):
    """정지 몹도 잡는다: 캐릭터 근접 빨간 이름표(몹 후보) 목록."""
    if char is None:
        return []
    cx, cy = char[:2]
    mobs = []
    for x, y, area, _rect in red_name_candidates(cur):
        d = np.hypot(x - cx, y - cy)
        if d <= NEAR_RADIUS:
            # 이름표 아래 몸체를 노린다(실측: 이름 아래 약 30px)
            mobs.append((int(x), int(y + 30), area))
    return sorted(mobs, key=lambda m: -m[2])


def near_mobs(prev, cur, char):
    """캐릭터 주변 근접 이동체(몹) 목록 — 프레임 차분 + 반경 필터."""
    if char is None:
        return []
    cx, cy = char[:2]
    diff = cv2.absdiff(prev, cur).max(axis=2)
    _, th = cv2.threshold(diff, 35, 255, cv2.THRESH_BINARY)
    th = cv2.dilate(th, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mobs = []
    for c in contours:
        area = cv2.contourArea(c)
        if not (150 <= area <= 6000):
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        mx, my = x + bw // 2, y + bh // 2
        # 캐릭터 본인 몸통(가까움)은 제외: 살짝 아래쪽 중심에서 벗어난 것만
        if np.hypot(mx - cx, my - cy) <= NEAR_RADIUS and \
                np.hypot(mx - cx, my - cy) > 60:
            mobs.append((int(mx), int(my), int(area)))
    return sorted(mobs, key=lambda m: -m[2])


class ExtHpSource:
    """크롬 확장(linc-vision-ext → ext_vision /hp) 네이티브 HP 판독 소스.

    사용자 지시(2026-09-15): 'HUD를 크롬익스텐션으로 개발하라니까'. CDP
    캡처는 1280x960 원본을 창 크기로 확대한 화면을 다시 읽어 보간 얼룩·
    시프트로 OCR이 흔들렸다(BTS-1033250/1033460/1033467). 확장은 video
    엘리먼트에서 네이티브 픽셀을 직접 뽑고 비율 스케일링으로 rect를
    맞춘다(실측 2026-09-15: 20/20 판독 성공). probe()는 실패 시 None —
    호출부에서 CDP hp_read로 폴백한다.
    """

    def __init__(self, url=EXT_HP_URL, timeout=1.5):
        self.url = url
        self.timeout = timeout

    def _fetch(self):
        try:
            with urllib.request.urlopen(self.url, timeout=self.timeout) as r:
                payload = json.loads(r.read().decode())
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def probe(self):
        """(cur, hp_max) 반환. 형식이 유효하지 않으면 None."""
        payload = self._fetch()
        if payload is None:
            return None
        cur, mx = payload.get("hp"), payload.get("hp_max")
        if not (isinstance(cur, int) and isinstance(mx, int)):
            return None
        if mx <= 0 or cur < 0 or cur > mx:
            return None
        return cur, mx

    def read(self):
        """HP 비율(가드 없는 원시값). 확장 게이지 판독값(ratio) 우선, 숫자
        OCR 폴백. 급변 가드는 read_hp_source의 hp_guard로 경로 통합 —
        이중 상태가 서로 어긋나면 오독이 유보를 뚫는다(2차 사고)."""
        payload = self._fetch()
        if payload is None:
            return None
        ratio = payload.get("ratio")
        if isinstance(ratio, (int, float)) and 0.0 <= ratio <= 1.0:
            return float(ratio)
        cur, mx = payload.get("hp"), payload.get("hp_max")
        if isinstance(cur, int) and isinstance(mx, int) and 0 < mx and 0 <= cur <= mx:
            return cur / mx
        return None


def calibrate_hud(src, need=3, tries=8, delay=2.5):
    """사냥 진입 전 HUD 확보 게이트(사용자 지시 2026-09-15: '막대를 처음에
    제대로 파악하고 진입하라꼬'). HP 숫자를 연속 need회 일관(hp_max 동일)
    판독해야 진입을 승인한다. 실패 시 None — 호출부는 사냥을 시작하지 않는다.
    종전엔 캘리브레이션 없이 진입해 HUD가 어긋난 채 사냥하다 'HP 판독 불가
    12회'로 중단됐다(BTS-1033460).
    """
    streak = 0
    last = None
    for _ in range(tries):
        if STOP.exists():
            return None
        got = src.probe()
        if got is None:
            streak = 0
            last = None
        else:
            streak = streak + 1 if (last and got[1] == last[1]) else 1
            last = got
            if streak >= need:
                return got
        time.sleep(delay)
    return None


def calibrate_cdp(w, need=3, tries=8, delay=2.5):
    """CDP 경로 캘리브레이션(확장 경로 확보 실패 시 폴백 검증)."""
    streak = 0
    for _ in range(tries):
        if STOP.exists():
            return None
        try:
            hp = hp_read(w.capture())
        except Exception:
            hp = None
        streak = streak + 1 if hp is not None else 0
        if streak >= need:
            return hp
        time.sleep(delay)
    return None


_HP_GUARD = {"last": None, "streak": 0}


def hp_guard(ratio):
    """경로 통합 HP 급변 가드(2026-09-15 2차 사고).

    확장(ExtHpSource)으로 읽다가 CDP hp_read로 폴백하는 순간, CDP 쪽
    가드의 prev(_LAST_HP)가 갱신된 적이 없어 무방비로 오독값이 통과했다
    ('223'→'23' 0.11 오판 → 이탈 클릭). 판독 경로와 무관하게 '최종 채택값'
    기준으로 유보한다.

    streak 방식: 직전 채택값 대비 급변(±0.30)은 첫 프레임 유보(prev 유지
    — 오독이 prev를 오염시키지 않는다), 같은 방향이 연속 2회면 진짜
    급변으로 승인한다(한 루프 지연).
    """
    if ratio is None:
        return None
    prev = _HP_GUARD["last"]
    if prev is not None and abs(ratio - prev) > 0.30:
        _HP_GUARD["streak"] += 1
        if _HP_GUARD["streak"] >= 2:
            _HP_GUARD["last"] = ratio
            _HP_GUARD["streak"] = 0
            return ratio
        return prev
    _HP_GUARD["last"] = ratio
    _HP_GUARD["streak"] = 0
    return ratio


def post_bot_status(ratio, kills=None, note=None):
    """봇 판독값을 ext_vision에 게시 — 크롬 익스텐션 HUD UI 데이터.

    실패해도 봇 동작에 영향 없음(UI 전용 채널)."""
    try:
        payload = {"ratio": ratio}
        if kills is not None:
            payload["kills"] = kills
        if note:
            payload["note"] = note
        req = urllib.request.Request(
            "http://127.0.0.1:17311/bot-hp",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=1.0).close()
    except Exception:
        pass


def main():
    STOP.unlink(missing_ok=True)
    w = CdpWindow(port=EXT_PORT)
    ext_hp = ExtHpSource()
    log("사냥 진입 전 HUD 캘리브레이션(확장 네이티브 판독)")
    base = calibrate_hud(ext_hp)
    if base is None:
        log("확장 HUD 캘리브레이션 실패 — CDP 경로로 재확인")
        if calibrate_cdp(w) is None:
            log("HUD 캘리브레이션 실패(확장+CDP 모두) — 사냥 진입 보류(사망 방지)")
            return
        log("CDP HUD 확보 — 사냥 시작(확장 경로는 회복 시 자동 우선)")
    else:
        log(f"HUD 확보: HP {base[0]}/{base[1]} — 사냥 시작")

    def read_hp_source(window):
        """HP 소스. 2026-09-15 15:0x: video 소스 HUD 밴드(y720)가 재접속
        후 레이아웃 어긋남(확장 스트립 게이지 폭 281px = 트랙 272 초과,
        ratio 0.58 vs CDP 화면 판독 0.985) — video 소스 값(ratio/숫자)을
        재실측 전까지 끊고 검증된 CDP 화면 판독(동적 rect+가드)을 우선
        한다. ext 경로는 CDP 실패 시 폴백."""
        ratio = hp_read(window.capture())
        if ratio is None:
            ratio = ext_hp.read()
        guarded = hp_guard(ratio)
        post_bot_status(guarded, kills=main.kills)
        return guarded

    log("한 칸 거리 사냥 시작(이동 없음, 근접 몹만)")
    kills = 0
    main.kills = 0
    hp_unread = 0
    prev = None
    potion = PotionKeys(read=read_hp_source)
    last_combat = time.monotonic()
    skill_last, skill_count = {}, {}
    func_last = {}
    while not STOP.exists():
        try:
            if not w.active():
                time.sleep(5)
                continue
            cur = w.capture()
            hp = read_hp_source(w)
            potion_delayed = False
            if hp is None:
                # HP 판독 불가 = 물약/이탈 모두 무력. 이 상태로 몹을 치면
                # 사망 경로다(리뷰). 공격 보류, 지속 시 사망 방지 중단.
                hp_unread += 1
                if hp_unread >= 12:
                    log("HP 판독 불가 지속 — 사냥 중단(사망 방지)")
                    break
                log(f"HP 판독 불가({hp_unread}/12): 공격 보류")
                time.sleep(2.5)
                continue
            hp_unread = 0
            settings = load_settings()
            now = time.monotonic()
            act = decide({
                "window_ok": True,
                "dead": hp is not None and hp <= 0.01,
                "hp": hp,
                "mp": None,
                "weight": None,
                "last_combat_age_sec": now - last_combat,
                "potions_empty": False,
            }, settings)
            if act.kind == STOP:
                log(act.reason + " — 사냥 중단")
                break
            if act.kind == RETURN:
                log(f"{act.reason} ({act.key})")
                try:
                    w.key(act.key)
                except Exception as exc:
                    log(f"귀환 키 실패: {exc}")
                time.sleep(1.0)
                continue
            if NOMOUSE.exists():
                # 마우스 금지 모드(사용자 지시): 몹 클릭·이탈 클릭 모두
                # 하지 않는다. 물약(F5 키)은 마우스가 아니므로 계속
                # 담당한다(2026-09-15 사고: 이 브랜치에서 potion.check를
                # 건너뛰어 HP가 0.58까지 떨어지는 동안 물약이 끊겼다).
                result = potion.check(w, hp)
                if result == EXHAUSTED:
                    log("물약 재고 소진 — 사냥 중단(사망 방지)")
                    break
                # HP 폴링 0.7초(사용자 지시 '감지가 늦으면 죽는다') —
                # 종전 2.0초 대비 감지 지연 1/3.
                time.sleep(0.35)
                continue
            result = potion.check(w, hp)
            if result == EXHAUSTED:
                log("물약 재고 소진 — 사냥 중단(사망 방지)")
                break
            potion_delayed = result == USED  # 물약 후에도 몹 공격은 이어간다
            sk = next_skill(settings.get("attack_skills") or [], hp, None, now, skill_last, skill_count)
            if sk and sk.get("key"):
                try:
                    w.key(sk["key"])
                    skill_last[sk["id"]] = now
                    skill_count[sk["id"]] = skill_count.get(sk["id"], 0) + 1
                    log(f"공격 마법 {sk.get('name')} ({sk['key']})")
                except Exception as exc:
                    log(f"스킬 키 실패: {exc}")
            fi = next_item(settings.get("func_items") or [], now, func_last, {"hp": hp})
            if fi and fi.get("hotkey"):
                try:
                    w.key(fi["hotkey"])
                    func_last[fi.get("itemId") or fi.get("name")] = now
                    log(f"기능 아이템 {fi.get('name')} ({fi['hotkey']})")
                except Exception as exc:
                    log(f"기능 아이템 키 실패: {exc}")
            if prev is None or prev.shape != cur.shape:
                prev = cur
                time.sleep(2.5)
                continue
            char = find_character(cur)
            mobs = near_mobs(prev, cur, char) or near_named_mobs(cur, char)
            prev = cur
            if not mobs:
                time.sleep(1.5 if potion_delayed else 2.5)
                continue
            mx, my, area = mobs[0]
            yield_click(w, mx, my)
            last_combat = time.monotonic()
            kills += 1
            main.kills = kills
            log(f"근접 몹 공격 #{kills}: ({mx},{my}) 면적={area} HP={hp}")
            time.sleep(4.0)  # 자동전투 진행 대기
            prev = None      # 전투 후 재기준
        except SystemExit:
            break
        except UserBusy as exc:
            log(str(exc))
            prev = None
            time.sleep(2.5)
        except Exception as exc:
            log(f"오류: {exc} — 재접속")
            time.sleep(5)
            try:
                w.close()
            except Exception:
                pass
            try:
                w = CdpWindow(port=EXT_PORT)
            except Exception:
                pass
    log(f"종료 — 공격 {kills}회")


if __name__ == "__main__":
    main()
