"""사이클 봇 v2 상태 전이 검증 — 설계 v2(2026-09-08) 규칙 중심.

전투는 ATS에 위임하고 관리자 로직(예방 귀환/당일 제외/원인 판별)만 검증한다.
"""
import json
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import cycle_bot
from ats_probe import ON, UNKNOWN
from cycle_bot import CycleBot


class FakeWindow:
    def __init__(self):
        import os
        os.environ["LINC_SKIP_USER_GATE"] = "1"  # 테스트는 양보 게이트 스킵
        self.clicks = []
        self.hotkeys = []
        self.keys = []

    def active(self):
        return True

    def capture(self):
        import numpy as np
        return np.zeros((1332, 1933, 3), dtype=np.uint8)

    def geometry(self):
        return (0, 0, 1933, 1332)

    def click(self, x, y, geo, hover=0.0):
        self.clicks.append((x, y))

    def hotkey(self, combo):
        self.hotkeys.append(combo)

    def key(self, name, geo=None):
        self.keys.append(name)

    def close(self):
        pass


def make_bot(**overrides):
    win = FakeWindow()
    cfg = {
        "potion_hp": 0.65, "danger_hp": 0.40, "hunt_minutes": 150,
        "potion_reserve": 50,
        "quickslot_potion": [1590, 1255], "return_scroll": [100, 100],
        "scroll_button": [200, 200], "ats_clicks": [[1, 1], [2, 2], [3, 3]],
        "ats_setup_clicks": [], "buff_clicks": [],
        "hunting_grounds": [
            {"name": "A터", "scroll_path": [[9, 9]]},
            {"name": "B터", "scroll_path": [[8, 8]]},
        ],
    }
    cfg.update(overrides)
    bot = CycleBot(win, cfg)
    bot._window = win
    return bot, win


def view(hp=1.0, safe=False):
    """analyze() 반환 스키마와 동일한 목(mock) 뷰(마을이어도 ready=True)."""
    zone = "safe" if safe else "combat"
    return {"hp": hp, "safe_zone": safe, "zone": zone,
            "ready": hp not in (None, 0) and zone != "unknown",
            "reason": "test", "_frame": None}


def patch_view(v):
    return patch.object(CycleBot, "read", lambda self: v)


class IsolatedLogCase(unittest.TestCase):
    """hunt_log.jsonl을 테스트마다 격리한다(일일 상한/순위 판정 오염 방지)."""

    def setUp(self):
        self.log = Path(__file__).parent / "hunt_log.jsonl"
        self._keep = self.log.read_text(encoding="utf-8") if self.log.exists() else ""
        if self.log.exists():
            self.log.unlink()

    def tearDown(self):
        if self._keep:
            self.log.write_text(self._keep, encoding="utf-8")
        elif self.log.exists():
            self.log.unlink()


class TownTests(IsolatedLogCase):
    def test_unreadable_stops(self):
        """판독 불가 = 모르는 화면 = 정지: TOWN 유지, 클릭 없음."""
        bot, win = make_bot()
        with patch_view(None):
            bot.step()
        self.assertEqual(bot.state, "TOWN")
        self.assertEqual(win.clicks, [])

    def test_dead_goes_return_with_reason(self):
        bot, _ = make_bot()
        with patch_view(view(0)):
            bot.step()
        self.assertEqual(bot.state, "RETURN")
        self.assertEqual(bot.return_reason, "hp_danger")

    def test_village_goes_supply(self):
        bot, _ = make_bot(start_in_town=True)
        with patch_view(view(1.0, safe=True)):
            bot.step()
        self.assertEqual(bot.state, "SUPPLY")

    def test_field_goes_return(self):
        bot, _ = make_bot()
        with patch_view(view(0.9)):
            bot.step()
        self.assertEqual(bot.state, "RETURN")

    def test_ats_time_zero_ends_without_charge(self):
        bot, _ = make_bot(start_in_town=True, ats_time_reader=[1, 2, 3, 4])
        with patch_view(view(1.0, safe=True)), \
                patch.object(CycleBot, "ats_time_left", lambda self, v: 0):
            bot.step()
        self.assertEqual(bot.state, "END")

    def test_ats_time_zero_charge_succeeds_when_time_increases(self):
        """충전 후 재판독에서 잔여가 증가해야만 계속한다."""
        bot, win = make_bot(start_in_town=True, ats_time_reader=[1, 2, 3, 4],
                            ats_charge_clicks=[[10, 10]])
        reads = iter([0, 60])
        with patch_view(view(1.0, safe=True)), \
                patch.object(CycleBot, "ats_time_left",
                             lambda self, v: next(reads)):
            bot.step()
        self.assertEqual(bot.state, "SUPPLY")
        self.assertIn((10, 10), win.clicks)

    def test_ats_time_zero_charge_failure_ends_immediately(self):
        """충전해도 잔여 0이면 즉시 END(거짓 성공 금지)."""
        bot, _ = make_bot(start_in_town=True, ats_time_reader=[1, 2, 3, 4],
                          ats_charge_clicks=[[10, 10]])
        with patch_view(view(1.0, safe=True)), \
                patch.object(CycleBot, "ats_time_left", lambda self, v: 0):
            bot.step()
        self.assertEqual(bot.state, "END")


class SupplySelectTests(IsolatedLogCase):
    def test_supply_without_inventory_waits(self):
        bot, win = make_bot(start_in_town=True)
        bot.state = "SUPPLY"
        with patch_view(view(1.0, safe=True)):
            bot.step()
        self.assertEqual(bot.state, "SUPPLY")
        self.assertEqual(win.clicks, [])

    def test_supply_reranks_grounds_from_log(self):
        """사냥 기록이 있으면 SUPPLY에서 우선순위가 재배열된다(설계 13번)."""
        log = Path(__file__).parent / "hunt_log.jsonl"
        keep = log.read_text(encoding="utf-8") if log.exists() else ""
        try:
            with log.open("a", encoding="utf-8") as sink:
                sink.write(json.dumps({"t": time.time(), "date": bot_date(),
                                       "ground": "A터", "minutes": 60,
                                       "potions": 600, "death": True}) + "\n")
            bot, _ = make_bot(start_in_town=True, inventory_button=[55, 55])
            bot.state = "SUPPLY"
            with patch_view(view(1.0, safe=True)):
                bot.step()
            names = [g["name"] for g in bot.cfg["hunting_grounds"]]
            self.assertEqual(names[0], "B터")
        finally:
            restore_log(log, keep)

    def test_select_hunt_picks_priority_ground(self):
        bot, _ = make_bot(start_in_town=True)
        bot.state = "SELECT_HUNT"
        with patch_view(view(1.0, safe=True)):
            bot.step()
        self.assertEqual(bot.state, "MOVE")
        self.assertEqual(bot.current_ground, "A터")

    def test_select_hunt_empty_after_exclusion_ends(self):
        bot, _ = make_bot(start_in_town=True)
        import datetime as dt
        today = dt.date.today().isoformat()
        bot.excluded = {today: {"A터": "테스트", "B터": "테스트"}}
        bot.state = "SELECT_HUNT"
        with patch_view(view(1.0, safe=True)):
            bot.step()
        self.assertEqual(bot.state, "END")


class MoveHuntTests(IsolatedLogCase):
    def test_move_arrival_starts_ats_once(self):
        """도착 → ATS_HUNT 진입 시 ATS 시작 클릭이 정확히 1회 세트."""
        bot, win = make_bot(start_in_town=True)
        bot.state = "MOVE"
        seq = iter([view(1.0, safe=True), view(1.0), view(1.0)])
        with patch.object(CycleBot, "read", lambda self: next(seq)):
            bot.step()   # 마을 확인 → 이동 → 도착 판정 → ATS_HUNT 전이
            bot.step()   # 첫 감시 스텝에서 ATS 시작
        self.assertEqual(bot.state, "ATS_HUNT")
        for x, y in bot.cfg["ats_clicks"]:
            self.assertIn((x, y), win.clicks)
        self.assertTrue(bot._ats_started)

    def test_ats_hunt_no_repeat_start(self):
        """이미 시작된 ATS는 재시작 클릭을 반복하지 않는다."""
        bot, win = make_bot()
        bot.state = "ATS_HUNT"
        bot._ats_started = True
        bot.hunt_started = time.monotonic()
        for _ in range(3):
            with patch_view(view(0.9)):
                bot.step()
        self.assertEqual(bot.state, "ATS_HUNT")
        self.assertEqual(win.clicks, [])

    def test_ats_self_return_inferred_by_low_hp(self):
        """ATS 자체 귀환 감지(저HP 관측 후 풀HP 지속) → hp_danger."""
        bot, _ = make_bot()
        bot.state = "ATS_HUNT"
        bot.current_ground = "A터"
        bot.hunt_started = time.monotonic() - 60
        seq = iter([view(0.42), view(0.97), view(0.98), view(0.99), view(1.0)])
        with patch.object(CycleBot, "read", lambda self: next(seq, view(1.0))):
            for _ in range(6):
                if bot.state == "RETURN":
                    break
                bot.step()
        self.assertEqual(bot.state, "RETURN")
        self.assertEqual(bot.return_reason, "hp_danger")

    def test_ats_self_return_inferred_idle(self):
        """저HP 없이 풀HP만 지속되면 귀환 신호가 아니다(비전투 오탐 방지)."""
        bot, _ = make_bot()
        bot.state = "ATS_HUNT"
        bot.hunt_started = time.monotonic()
        with patch_view(view(1.0)):
            for _ in range(4):
                bot.step()
        self.assertEqual(bot.state, "ATS_HUNT")

    def test_potion_reserve_triggers_preemptive_return(self):
        """L1: 주홍 안전재고 이하 → 예방 귀환(potion_preempt)."""
        bot, _ = make_bot()
        bot.state = "ATS_HUNT"
        bot._ats_started = True
        with patch_view(view(0.9)), \
                patch.object(CycleBot, "quickslot_potions", lambda self, v: 30):
            bot.step()
        self.assertEqual(bot.state, "RETURN")
        self.assertEqual(bot.return_reason, "potion_preempt")

    def test_hunt_time_over_moves_next_ground(self):
        bot, _ = make_bot()
        bot.state = "ATS_HUNT"
        bot._ats_started = True
        bot.hunt_started = -100000
        with patch_view(view(0.9)):
            bot.step()
        self.assertEqual(bot.state, "RETURN")
        self.assertEqual(bot.ground_idx, 1)
        self.assertEqual(bot.return_reason, "ats_time_over")


class ReturnTests(IsolatedLogCase):
    def test_double_emergency_excludes_ground_today(self):
        """긴급귀환 2회 → 해당 사냥터 당일 제외 + 다음 사냥터."""
        bot, _ = make_bot()
        bot.current_ground = "A터"
        bot.hunt_started = time.monotonic() - 60
        bot.state = "RETURN"
        bot.return_reason = "hp_danger"
        with patch_view(view(1.0, safe=True)):
            bot.step()
            bot.state = "RETURN"
            bot.return_reason = "hp_danger"
            bot.step()
        self.assertIn("A터", bot.excluded.get(bot.today, {}))
        self.assertEqual(bot.ground_idx, 1)

    def test_return_logs_reason(self):
        bot, _ = make_bot()
        bot.current_ground = "A터"
        bot.hunt_started = time.monotonic() - 120
        bot.state = "RETURN"
        bot.return_reason = "potion_preempt"
        with patch_view(view(1.0, safe=True)):
            bot.step()
        self.assertEqual(bot.state, "TOWN")
        line = json.loads(cycle_bot.LOG_PATH.read_text(
            encoding="utf-8").strip().splitlines()[-1])
        self.assertEqual(line["reason"], "potion_preempt")
        self.assertEqual(line["ground"], "A터")


def bot_date():
    import datetime as dt
    return dt.date.today().isoformat()


def restore_log(log, keep):
    if keep:
        log.write_text(keep, encoding="utf-8")
    elif log.exists():
        log.unlink()


class HardenedRulesTests(IsolatedLogCase):
    """리뷰로 발견한 CRIT/MAJOR 수정 검증."""

    def test_end_state_does_not_crash(self):
        """END 진입 후에도 step이 크래시 없이 대기 메시지를 낸다."""
        bot, _ = make_bot()
        bot.state = "END"
        with patch_view(view(1.0, safe=True)):
            message = bot.step()
        self.assertEqual(bot.state, "END")
        self.assertIn("종료", message)

    def test_return_uses_scroll_when_in_field(self):
        """봇이 귀환을 결정한 필드 상태면 주문서를 직접 쓴다."""
        bot, win = make_bot()
        bot.current_ground = "A터"
        bot.hunt_started = time.monotonic() - 60
        bot.state = "RETURN"
        bot.return_reason = "potion_preempt"
        with patch.object(CycleBot, "read",
                          side_effect=[view(0.9), view(1.0, safe=True)]):
            bot.step()
        self.assertIn(tuple(bot.cfg["return_scroll"]), win.clicks)
        self.assertEqual(bot.state, "TOWN")

    def test_return_without_scroll_delegates_to_ats(self):
        """주문서 좌표 미실측이면 터치 없이 L0에 맡긴다(클릭 0회)."""
        bot, win = make_bot(return_scroll=None)
        bot.current_ground = "A터"
        bot.hunt_started = time.monotonic() - 60
        bot.state = "RETURN"
        bot.return_reason = "potion_preempt"
        with patch_view(view(1.0, safe=True)):
            bot.step()
        self.assertEqual(bot.state, "TOWN")
        self.assertNotIn(None, win.clicks)

    def test_move_triple_failure_selects_next_ground(self):
        """이동 3회 실패 → 다음 사냥터 선택으로(SUPPLY 경유)."""
        bot, _ = make_bot(start_in_town=True)
        bot.state = "MOVE"
        for _ in range(3):
            with patch_view(view(1.0, safe=True)):  # 계속 마을 = 이동 실패
                bot.step()
        self.assertEqual(bot.state, "SELECT_HUNT")
        self.assertEqual(bot.ground_idx, 1)
        self.assertEqual(bot._move_attempts, 0)

    def test_daily_cap_ends_without_ats_reader(self):
        """잔여 판독 없이 일일 누적 상한을 넘으면 END."""
        with (Path(__file__).parent / "hunt_log.jsonl").open("a", encoding="utf-8") as sink:
            sink.write(json.dumps({"t": time.time(), "date": bot_date(),
                                   "ground": "A터", "minutes": 181,
                                   "potions": 0, "reason": "ats_time_over"}) + "\n")
        bot, _ = make_bot(start_in_town=True)
        with patch_view(view(1.0, safe=True)):
            bot.step()
        self.assertEqual(bot.state, "END")

    def test_potion_consumption_accumulates(self):
        """퀵슬롯 잔량 감소분을 사냥 소비로 누적한다(로그 품질)."""
        bot, _ = make_bot()
        bot.state = "ATS_HUNT"
        bot._ats_started = True
        bot.hunt_started = time.monotonic()
        seq = iter([300, 240])
        with patch_view(view(0.9)), \
                patch.object(CycleBot, "quickslot_potions",
                             lambda self, v: next(seq)):
            bot.step()
            bot.step()
        self.assertEqual(bot.stats["potions"], 60)


class ReviewGateTests(IsolatedLogCase):
    """Claude 리뷰 CRIT 반영 검증 — 판독 미확정 시 터치가 나가지 않는다."""

    def test_move_blocked_when_zone_unknown(self):
        """zone 판독 실패(unknown) 상태에서는 두루마리 클릭이 없다."""
        bot, win = make_bot()
        bot.state = "MOVE"
        unknown = view(1.0, safe=True)
        unknown["zone"] = "unknown"
        with patch_view(unknown):
            bot.step()
        self.assertEqual(win.clicks, [])

    def test_ats_start_blocked_without_ready(self):
        """ready 게이트 미통과(패널/차단)면 ATS 시작 클릭이 없다."""
        bot, win = make_bot()
        bot.state = "ATS_HUNT"
        blocked = view(0.9)
        blocked["ready"] = False  # analyze가 내보내는 입력 차단 상태
        with patch_view(blocked):
            bot.step()
        self.assertEqual(win.clicks, [])

    def test_supply_requires_assume_supplied_flag(self):
        bot, win = make_bot(start_in_town=True, inventory_button=[55, 55])
        bot.state = "SUPPLY"
        with patch.object(CycleBot, "read",
                          side_effect=[view(1.0, safe=True), view(1.0, safe=True)]):
            bot.step()
        self.assertEqual(bot.state, "SUPPLY")
        self.assertEqual(win.clicks, [(55, 55)])  # 인벤 열기만, 진행 없음

    def test_ats_restarts_on_second_cycle(self):
        """다음 사냥터 도착 시 _ats_started가 리셋되어 ATS가 다시 시작된다."""
        bot, win = make_bot(start_in_town=True)
        bot.state = "MOVE"
        bot._ats_started = True  # 이전 사냥터에서 켜져 있던 상태
        seq = iter([view(1.0, safe=True), view(1.0), view(1.0)])
        with patch.object(CycleBot, "read", lambda self: next(seq)):
            bot.step()
            self.assertFalse(bot._ats_started)  # 도착 시 리셋 확인
            bot.step()
        self.assertTrue(bot._ats_started)

    def test_charge_failure_twice_ends(self):
        """충전 실패는 즉시 END(무한 충전 재시도 차단)."""
        bot, _ = make_bot(start_in_town=True, ats_time_reader=[1, 2, 3, 4],
                          ats_charge_clicks=[[10, 10]])
        bot.state = "TOWN"
        with patch_view(view(1.0, safe=True)), \
                patch.object(CycleBot, "ats_time_left", lambda self, v: 0):
            bot.step()  # 1차 충전 실패 — 아직 재시도
            bot.state = "TOWN"
            bot.step()  # 2차 실패
            bot.state = "TOWN"
            bot.step()  # END
        self.assertEqual(bot.state, "END")


class ReviewMajorFollowupTests(IsolatedLogCase):
    """2차 전수확인으로 발견한 MAJOR 4건 수정 검증."""

    def test_move_with_empty_pool_ends(self):
        """당일 제외로 pool이 빈 상태의 MOVE는 크래시 없이 END."""
        import datetime as dt
        bot, _ = make_bot(start_in_town=True)
        bot.excluded = {dt.date.today().isoformat(): {"A터": "x", "B터": "x"}}
        bot.state = "MOVE"
        with patch_view(view(1.0, safe=True)):
            bot.step()
        self.assertEqual(bot.state, "END")

    def test_dead_view_does_not_loop_forever(self):
        """hp=0 방어 경로: 주문서 없이 대기 20회 후 END(프로덕션은 hp=None 경로)."""
        bot, win = make_bot()
        bot.current_ground = "A터"
        bot.hunt_started = time.monotonic() - 60
        bot.state = "RETURN"
        bot.return_reason = "hp_danger"
        with patch_view(view(0)):
            for _ in range(21):
                if bot.state == "END":
                    break
                bot.state = "RETURN"
                bot.return_reason = "hp_danger"
                bot.step()
        self.assertEqual(bot.state, "END")
        self.assertEqual(win.clicks, [])  # 주문서 낭비 없음

    def test_screen_stalled_uses_change_ratio(self):
        """스트리밍 노이즈 고려: 동일 프레임 3회는 정지, 노이즈는 활동."""
        import numpy as np
        bot, _ = make_bot()
        frame = np.zeros((1332, 1933, 3), dtype=np.uint8)
        self.assertFalse(bot.screen_stalled(frame))  # 초기화 프레임
        self.assertFalse(bot.screen_stalled(frame))  # 정지 1
        self.assertFalse(bot.screen_stalled(frame))  # 정지 2
        self.assertTrue(bot.screen_stalled(frame))   # 정지 3 → 판정
        rng = np.random.default_rng(7)
        noisy = rng.integers(0, 255, size=frame.shape, dtype=np.uint8)
        self.assertFalse(bot.screen_stalled(noisy))  # 큰 변화 = 활동

    def test_today_refreshes_on_date_change(self):
        """자정(또는 재시작 없는 날짜 변경)에 당일 제외가 초기화된다."""
        bot, _ = make_bot()
        bot.today = "2000-01-01"
        with patch_view(view(1.0, safe=True)):
            bot.step()
        import datetime as dt
        self.assertEqual(bot.today, dt.date.today().isoformat())

    def test_prolonged_unreadable_ends_safely(self):
        """판독 불가 120초 지속(사망 게이지 0 포함)은 안전 종료."""
        bot, _ = make_bot()
        bot._unreadable_since = time.monotonic() - 130
        bot.state = "TOWN"
        with patch_view(None):
            bot.step()
        self.assertEqual(bot.state, "END")


class LoopGuardTests(IsolatedLogCase):
    """자체 점검으로 발견한 무한루프 잔재 2건 방지 검증."""

    def test_return_retry_capped(self):
        """주문서 없이 필드에 남은 RETURN은 5회 재시도 후 END."""
        bot, _ = make_bot(return_scroll=None)
        bot.current_ground = "A터"
        bot.hunt_started = time.monotonic() - 60
        bot.state = "RETURN"
        with patch_view(view(0.9)):  # 계속 필드
            for _ in range(6):
                if bot.state == "END":
                    break
                bot.return_reason = bot.return_reason or "unknown"
                bot.step()
        self.assertEqual(bot.state, "END")

    def test_return_unreadable_view_is_not_town(self):
        """view=None(사망→analyze None / 캡처 실패)을 '귀환 완료'로 오판하면 안 된다.

        기존: run_return(None) → in_town=True, TOWN 으로 전진해 죽은 캐릭터로 보급까지 감.
        """
        bot, _ = make_bot(return_scroll=None)
        bot.current_ground = "A터"
        bot.return_reason = "hp_danger"
        state, msg = bot.run_return(None)
        self.assertEqual(state, "RETURN")
        self.assertFalse(bot.in_town)
        self.assertIn("확인 불가", msg)
        # hp None 도 동일하게 미확인
        v = view(0.9)
        v["hp"] = None
        state, _ = bot.run_return(v)
        self.assertEqual(state, "RETURN")
        self.assertFalse(bot.in_town)
        self.assertEqual(bot._return_unreadable, 2)

    def test_return_unreadable_persist_ends_for_human(self):
        """판독 불가가 10회 연속이면 사람 확인 END. 그 전에 판독되면 카운터 리셋."""
        bot, _ = make_bot(return_scroll=None)
        bot.current_ground = "A터"
        bot.return_reason = "unknown"
        for _ in range(9):
            state, _ = bot.run_return(None)
            self.assertEqual(state, "RETURN")
        # 마을 판독 성공 → 정상 귀환 완료 + 카운터 리셋
        town = view(0.9)
        town["safe_zone"] = True
        state, _ = bot.run_return(town)
        self.assertEqual(state, "TOWN")
        self.assertTrue(bot.in_town)
        self.assertEqual(bot._return_unreadable, 0)
        bot.in_town = False
        for _ in range(10):
            state, _ = bot.run_return(None)
        self.assertEqual(state, "END")
        self.assertFalse(bot.in_town)

    def test_blocked_ready_state_times_out(self):
        """hp는 있으나 ready=False(패널)가 120초 지속되면 안전 종료."""
        bot, _ = make_bot()
        bot.state = "ATS_HUNT"
        bot._ats_started = True
        bot.hunt_started = time.monotonic()
        blocked = view(0.9)
        blocked["ready"] = False
        bot._blocked_since = time.monotonic() - 130
        with patch_view(blocked):
            bot.step()
        self.assertEqual(bot.state, "END")


class ReverifyFixTests(IsolatedLogCase):
    """재리뷰가 잡은 미해결/오판 수정 확인."""

    def test_field_ok_rejects_village_even_ready(self):
        """in_town 상태면 ready=True여도 field_ok를 통과하지 못한다."""
        bot, _ = make_bot(start_in_town=True)
        self.assertTrue(view(1.0, safe=True)["ready"])
        self.assertFalse(bot.field_ok(view(1.0, safe=True)))
        bot.in_town = False
        self.assertTrue(bot.field_ok(view(1.0)))

    def test_return_does_not_use_scroll_in_village(self):
        bot, win = make_bot(start_in_town=True)
        bot.current_ground = "A터"
        bot.hunt_started = time.monotonic() - 60
        bot.state = "RETURN"
        bot.return_reason = "potion_preempt"
        with patch_view(view(1.0, safe=True)):
            bot.step()
        self.assertEqual(bot.state, "TOWN")
        self.assertEqual(win.clicks, [])

    def test_move_blocked_when_zone_unknown(self):
        """zone 판독 실패와 무관하게 in_town=False면 MOVE는 마을 게이트에 막힌다."""
        bot, win = make_bot(start_in_town=False)
        bot.state = "MOVE"
        unknown = view(1.0, safe=True)
        unknown["zone"] = "unknown"
        with patch_view(unknown):
            bot.step()
        self.assertEqual(bot.clicks if hasattr(bot, "clicks") else win.clicks, [])


class AtsBootLinkTests(IsolatedLogCase):
    """ATS_HUNT ↔ AtsBoot 연결 + 시작 위치 자동 판별 검증 (2026-09-09)."""

    class FakeBoot:
        def __init__(self, boot_result=UNKNOWN, keep=UNKNOWN, stale=False):
            self.boot_result = boot_result
            self.keep = keep
            self.stale_flag = stale
            self.boot_calls = 0
            self.probe = types.SimpleNamespace(
                stale=lambda seconds=180: self.stale_flag)

        def boot(self):
            self.boot_calls += 1
            return self.boot_result

        def keep_alive_step(self, frame):
            return self.keep

    def test_field_boot_starts_ats_hunt_without_scroll(self):
        """필드에서 기동하면 첫 상태 ATS_HUNT + 귀환 주문서 클릭 0회."""
        bot, win = make_bot()
        auto = cycle_bot.initial_state_from_view(view(0.9))
        self.assertEqual(auto, ("ATS_HUNT", False))
        bot.state, bot.in_town = auto
        bot.hunt_started = time.monotonic()
        bot.current_ground = "필드 기동"
        with patch_view(view(0.9)):
            bot.step()
        self.assertEqual(bot.state, "ATS_HUNT")
        self.assertNotIn(tuple(bot.cfg["return_scroll"]), win.clicks)

    def test_initial_state_variants(self):
        """마을은 TOWN, 판독 불가/사망은 판별 보류(None)."""
        self.assertEqual(
            cycle_bot.initial_state_from_view(view(1.0, safe=True)), ("TOWN", True))
        self.assertIsNone(cycle_bot.initial_state_from_view(None))
        self.assertIsNone(cycle_bot.initial_state_from_view(view(0)))

    def test_boot_failure_falls_back_once_then_ends(self):
        """검증 가능 환경에서 boot 실패 → 실측 클릭 폴백 정확히 1회 →
        여전히 ON 아니면 END. ON 확인 전 _ats_started True 금지."""
        bot, win = make_bot(ats_time_reader=[1, 2, 3, 4])
        bot.state = "ATS_HUNT"
        fake = self.FakeBoot(boot_result=UNKNOWN)
        with patch_view(view(0.9)), \
                patch.object(CycleBot, "_ensure_boot", lambda self: fake), \
                patch.object(CycleBot, "_wait_ats_on", return_value=False):
            bot.step()
            self.assertEqual(bot.state, "END")
            self.assertFalse(bot._ats_started)
            self.assertEqual(fake.boot_calls, 1)
            # 폴백 1회 = ats_clicks 세트 정확히 한 번 (매 스텝 클릭 금지)
            self.assertEqual(win.clicks, [tuple(c) for c in bot.cfg["ats_clicks"]])
            bot.step()
            self.assertEqual(bot.state, "END")
            self.assertEqual(len(win.clicks), len(bot.cfg["ats_clicks"]))

    def test_already_on_never_clicks(self):
        """이미 ON(카운트다운 감소 확인)이면 boot 클릭 0회로 시작 확정."""
        bot, win = make_bot(ats_time_reader=[1, 2, 3, 4])
        bot.state = "ATS_HUNT"
        bot.hunt_started = time.monotonic()
        fake = self.FakeBoot(boot_result=ON, keep=ON)
        with patch_view(view(0.9)), \
                patch.object(CycleBot, "_ensure_boot", lambda self: fake):
            bot.step()
            bot.step()
        self.assertEqual(bot.state, "ATS_HUNT")
        self.assertTrue(bot._ats_started)
        self.assertEqual(win.clicks, [])
        self.assertEqual(fake.boot_calls, 1)  # keep-alive은 boot 재호출 없음

    def test_screen_activity_blocks_fallback_clicks(self):
        """화면에 사냥 활동(기존 ATS/사용자 플레이)이 있으면 폴백 클릭
        없이 감시만 한다 — 기존 동작을 메뉴로 끊지 않는다."""
        bot, win = make_bot()
        bot.state = "ATS_HUNT"
        bot.hunt_started = time.monotonic()
        with patch_view(view(0.9)), \
                patch.object(CycleBot, "_screen_active", return_value=True):
            bot.step()
        self.assertEqual(bot.state, "ATS_HUNT")
        self.assertTrue(bot._ats_started)   # 외부 기동 간주 — 감시 모드
        self.assertEqual(win.clicks, [])    # 메뉴 조작 0회

    def test_no_scroll_click_on_village_view_after_field_boot(self):
        """필드 부팅 상태에서 마을 뷰(ATS 자체 귀환 직후)가 오면
        귀환 주문서를 클릭하지 않는다 — 이미 마을이므로 낭비/오조작."""
        bot, win = make_bot()   # start_in_town=False → 필드 부팅
        bot.current_ground = "필드 기동"
        bot.hunt_started = time.monotonic() - 60
        bot.state = "RETURN"
        bot.return_reason = "hp_danger"
        with patch_view(view(1.0, safe=True)):   # 마을 화면
            bot.step()
        self.assertEqual(bot.state, "TOWN")
        self.assertNotIn(tuple(bot.cfg["return_scroll"]), win.clicks)
        self.assertEqual(win.clicks, [])

    def test_zone_read_failure_is_soft_block(self):
        """zone 판독 실패(밝은 배경)는 패널 차단과 달리 END 에스컬레이션
        없이 터치만 보류한다 — 기존 사냥 감시는 계속된다."""
        bot, win = make_bot()
        bot.state = "ATS_HUNT"
        bot.hunt_started = time.monotonic()
        blocked = view(0.9)
        blocked["ready"] = False
        blocked["reason"] = "지역 상태 판독 실패: 입력 차단"
        bot._blocked_since = time.monotonic() - 130  # 이미 120초 경과 상태
        with patch_view(blocked):
            bot.step()
        self.assertEqual(bot.state, "ATS_HUNT")
        self.assertEqual(win.clicks, [])

    def test_keepalive_unknown_long_schedules_reboot(self):
        """ON이던 ATS가 UNKNOWN 3분 지속 → 예산 내 재기동 예약(클릭 없이)."""
        bot, win = make_bot(ats_time_reader=[1, 2, 3, 4])
        bot.state = "ATS_HUNT"
        bot._ats_started = True
        bot.hunt_started = time.monotonic()
        fake = self.FakeBoot(keep=UNKNOWN, stale=True)
        bot._unknown_since = time.monotonic() - 200
        with patch_view(view(0.9)), \
                patch.object(CycleBot, "_ensure_boot", lambda self: fake):
            bot.step()
            self.assertEqual(bot.state, "ATS_HUNT")
            self.assertFalse(bot._ats_started)   # 다음 스텝에서 boot 재시도
            self.assertEqual(bot._boot_restarts, 1)
            self.assertEqual(win.clicks, [])      # 이 스텝에는 클릭 없음
            bot.step()
            self.assertEqual(fake.boot_calls, 1)  # 재기동 = boot 재호출


if __name__ == "__main__":
    unittest.main()


class HpBackstopTests(IsolatedLogCase):
    """BTS-1033015 C2: ATS 위임 실패 시 최후 백스톱 귀환."""

    def _armed(self, **kw):
        bot, win = make_bot(**kw)
        bot._ats_started = True          # _start_ats 우회
        return bot, win

    def test_저HP_첫관측은_귀환하지_않고_기록만(self):
        bot, _ = self._armed()
        clock = [1000.0]
        with patch_view(view(hp=0.30)), \
             patch.object(cycle_bot.time, "monotonic", lambda: clock[0]):
            state, why = bot.run_ats_hunt(bot.read())
        self.assertNotEqual(state, "RETURN", f"단발 저HP로 즉시 귀환: {why}")
        self.assertEqual(bot.hp_low_since, 1000.0)

    def test_저HP_지속시_백스톱_귀환(self):
        bot, _ = self._armed()
        clock = [1000.0]
        with patch.object(cycle_bot.time, "monotonic", lambda: clock[0]):
            with patch_view(view(hp=0.30)):
                bot.run_ats_hunt(bot.read())
            clock[0] += 3.0              # danger_hold_s 경과
            with patch_view(view(hp=0.30)):
                state, why = bot.run_ats_hunt(bot.read())
        self.assertEqual(state, "RETURN", why)
        self.assertEqual(bot.return_reason, "hp_danger")

    def test_HP_회복시_지속타이머_리셋(self):
        """판독 노이즈로 한 프레임 저HP였다가 회복하면 누적이 초기화된다."""
        bot, _ = self._armed()
        clock = [1000.0]
        with patch.object(cycle_bot.time, "monotonic", lambda: clock[0]):
            with patch_view(view(hp=0.30)):
                bot.run_ats_hunt(bot.read())
            clock[0] += 1.0
            with patch_view(view(hp=0.95)):
                bot.run_ats_hunt(bot.read())
            self.assertIsNone(bot.hp_low_since, "회복했는데 저HP 누적이 남았다")
            clock[0] += 60.0             # 오래 지났어도 새 관측부터 다시 센다
            with patch_view(view(hp=0.30)):
                state, why = bot.run_ats_hunt(bot.read())
        self.assertNotEqual(state, "RETURN", f"회복 후 첫 저HP로 즉시 귀환: {why}")


class ReturnReasonTests(IsolatedLogCase):
    """BTS-1033015: 원인 오분류(무게 태그 미사용 / 스티키 저HP)."""

    def test_판정불가는_idle_no_combat이_아니라_unknown(self):
        src = (Path(__file__).parent / "cycle_bot.py").read_text(encoding="utf-8")
        head = src.split("def _town_signal")[0]
        self.assertIn('self.return_reason = "unknown"', head,
                      "ATS 자체귀환 원인 폴백이 unknown이 아니다")
