"""아덴/드랍 줍기 전담 — F4 줍기 단축키 방식 (BTS-1033502, 2026-09-15).

사용자 지시: 'f4가 단축키'. 드랍 라벨(item_labels)이 보이면 F4 키로
줍는다 — 마우스 클릭(이동 클릭→재클릭) 전에 없이 nomouse 정책 유지.
성공 판정은 채팅창 '획득' 메시지(chat_watch)로만 한다. 연속 실패 시
짧은 대기 후 재시도(토글형 키 연타 방지).
분업: ATS=몹 사냥, onestep=물약, 이 스크립트=F4 줍기.
"""
import time
from pathlib import Path

from cdp_window import CdpWindow, EXT_PORT
from chat_watch import pickup_count
from item_labels import PICK_RECT, detect_labels, read_label_names
from item_tiers import tier_of
from linux_vision import find_character, red_name_candidates
from user_gate import user_active

RUNTIME = Path("/tmp/linc-bot-linux")
STOP = RUNTIME / "stop-aden"   # onestep과 STOP 분리(봇 교체 때 같이 죽는 간섭 방지)
NEAR_MOB_RADIUS = 350  # 접적 판정 반경(px) — 칼질 중 줍기 금지(2026-09-15
                        # 사용자 지시 '칼질중엔 줍지말기', 260→350 확대)
RETRY_GAP = 3.0        # 줍기 실패 후 재시도 간격(초)
FAIL_LIMIT = 3          # 연속 실패 상한 — 넘으면 긴 대기(드랍이 줍을 수
LONG_WAIT = 12.0        # 없는 상태일 수 있다: 멀리/이미 꽉 참 등)


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def main():
    STOP.unlink(missing_ok=True)
    w = CdpWindow(port=EXT_PORT)
    # 물약은 onestep 봇이 전담한다(2026-09-15 사고: aden이 같은 F5/F6를
    # 함께 누르며 게임 쿨다운 충돌로 양쪽 다 무반응 → HP 0.51 하락).
    picked = 0
    fails = 0
    log("F4 연속 줍기 시작(1회 1줍기 — 실측: 하나만 줍고 멈춤)")
    while not STOP.exists():
        try:
            if not w.active():
                time.sleep(5)
                continue
            img = w.capture()

            # 사용자 지시(2026-09-15): '몬스터랑 사냥중일때말고 사냥이
            # 없을때 주서라' — 캐릭터 근처 몹(빨간 이름표)이 있으면 접적
            # 상태로 보고 줍기를 보류한다(전투 흐름 방해 차단).
            char = find_character(img)
            if char is None:
                # 캐릭터를 못 찾으면 접적 판정 자체가 불가 — 보수적으로
                # 줍기를 보류한다(칼질 중일 가능성을 배제 못 함).
                time.sleep(1.0)
                continue
            cx, cy = char[:2]
            mobs = [(x, y) for x, y, _a, _r in red_name_candidates(img)
                    if (x - cx) ** 2 + (y - cy) ** 2 <= NEAR_MOB_RADIUS ** 2]
            if mobs:
                fails = 0
                log(f"접적(근처 몹 {len(mobs)}) — 칼질 중 줍기 보류")
                time.sleep(1.0)
                continue

            labels = read_label_names(img, detect_labels(img, PICK_RECT))
            # 등급 판별(사용자 지시 '고급템과 저급템 판별'): 저급 잡템은
            # 줍지 않는다. unknown은 줍는다(놓침 손해가 더 크다).
            good = [l for l in labels if tier_of(l.name) != "low"]
            lows = [l for l in labels if tier_of(l.name) == "low"]
            if lows and good:
                log(f"저급 {len(lows)}개 무시({lows[0].name!r}) · 고급 {len(good)}개")
            if not good:
                fails = 0
                time.sleep(2.0)
                continue
            labels = good

            # F4는 1회 1줍기(실측 2026-09-15: 여러 개 중 하나만 줍고 멈춤
            # — 사용자 보고). 드랍이 남아있는 동안 게임 쿨다운 간격으로
            # 연속 누른다. 사용자 조작 중엔 잠깐 양보.
            waited = 0
            while user_active() and waited < 6 and not STOP.exists():
                time.sleep(1.0)
                waited += 1
            before = pickup_count(img, w)
            # 사용자가 마우스로 조작 중이면 키만 스킵하고 잠시 양보
            waited = 0
            while user_active() and waited < 6 and not STOP.exists():
                time.sleep(1.0)
                waited += 1
            w.key("F4", w.geometry())
            time.sleep(1.0)
            gain = max(0, pickup_count(w.capture(), w) - before)
            if gain:
                picked += gain
                fails = 0
                log(f"F4 줍기 획득 {gain} (누적 {picked})")
            else:
                fails += 1
                if fails >= FAIL_LIMIT:
                    log(f"F4 연속 무획득 {fails} — 드랍이 멀 수 있음, {LONG_WAIT}s 대기")
                    time.sleep(LONG_WAIT)
                    fails = 0
                else:
                    time.sleep(RETRY_GAP)
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
    log(f"종료 — 줍기 성공 {picked}")


if __name__ == "__main__":
    main()
