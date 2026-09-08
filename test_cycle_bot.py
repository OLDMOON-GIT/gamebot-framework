"""사이클 봇 상태 전이 검증 — 사용자 설계(2026-09-08) 규칙 중심."""
import unittest
from unittest.mock import patch

import cycle_bot
from cycle_bot import CycleBot


class FakeWindow:
    def __init__(self):
        self.clicks = []
        self.active_flag = True

    def active(self):
        return self.active_flag

    def capture(self):
        import numpy as np, cv2
        return np.zeros((1332, 1933, 3), dtype=np.uint8)

    def geometry(self):
        return (0, 0, 1933, 1332)

    def click(self, x, y, geo, hover=0.0):
        self.clicks.append((x, y))

    def close(self):
        pass


def make_bot(hp=None, safe=False):
    win = FakeWindow()
    cfg = {
        "potion_hp": 0.65, "danger_hp": 0.50, "danger_seconds": 8,
        "hunt_minutes": 150, "quickslot_potion": [1590, 1255],
        "return_scroll": [100, 100], "scroll_button": [200, 200],
        "ats_clicks": [[1, 1], [2, 2], [3, 3]], "buff_clicks": [],
        "hunting_grounds": [
            {"name": "A터", "scroll_path": [[9, 9]]},
            {"name": "B터", "scroll_path": [[8, 8]]},
        ],
    }
    bot = CycleBot(win, cfg)
    bot._window = win
    view = {"hp": hp, "safe_zone": safe, "reason": "test", "_frame": None}
    return bot, win, view


def patch_view(view, alive=True):
    return patch.object(CycleBot, "read", lambda self: view if alive else None)


class StateMachineTests(unittest.TestCase):
    def test_boot_unreadable_stays(self):
        """판독 불가 = 모르는 화면 = 정지: BOOT 유지, 클릭 없음."""
        bot, win, _ = make_bot()
        with patch_view(None, alive=False):
            msg = bot.step()
        self.assertEqual(bot.state, "BOOT")
        self.assertEqual(win.clicks, [])

    def test_boot_dead_to_recover(self):
        bot, win, _ = make_bot(hp=0)
        with patch_view({"hp": 0, "safe_zone": False, "_frame": None}):
            bot.step()
        self.assertEqual(bot.state, "RECOVER")

    def test_boot_village_to_supply(self):
        bot, win, _ = make_bot(hp=1.0, safe=True)
        with patch_view({"hp": 1.0, "safe_zone": True, "_frame": None}):
            bot.step()
        self.assertEqual(bot.state, "SUPPLY")

    def test_boot_field_to_retreat(self):
        bot, win, _ = make_bot(hp=0.9, safe=False)
        with patch_view({"hp": 0.9, "safe_zone": False, "_frame": None}):
            bot.step()
        self.assertEqual(bot.state, "RETREAT")

    def test_supply_without_inventory_waits(self):
        """인벤 좌표 미실측이면 터치 없이 대기(사람 보급)."""
        bot, win, _ = make_bot(hp=1.0, safe=True)
        bot.state = "SUPPLY"
        with patch_view({"hp": 1.0, "safe_zone": True, "_frame": None}):
            bot.step()
        self.assertEqual(bot.state, "SUPPLY")
        self.assertEqual(win.clicks, [])

    def test_hunt_low_hp_clicks_potion_when_not_delegated(self):
        """ATS 물약 위임이 아니면 저체력에 봇이 직접 누른다."""
        bot, win, _ = make_bot(hp=0.5)
        bot.cfg["ats_potion"] = False
        bot.state = "HUNT"
        with patch_view({"hp": 0.5, "safe_zone": False, "_frame": None}):
            bot.step()
        self.assertIn((1590, 1255), win.clicks)

    def test_hunt_low_hp_delegates_to_ats_by_default(self):
        """기본은 ATS에 물약을 맡긴다: 저체력이어도 퀵슬롯 클릭 없음."""
        bot, win, _ = make_bot(hp=0.5)
        bot.state = "HUNT"
        with patch_view({"hp": 0.5, "safe_zone": False, "_frame": None}):
            bot.step()
        self.assertNotIn((1590, 1255), win.clicks)

    def test_hunt_survival_first_retreat(self):
        """HP<50% 지속 + 물약 무효 → 생존 우선 귀환(RETREAT)."""
        bot, win, _ = make_bot(hp=0.4)
        bot.state = "HUNT"
        bot.hp_low_since = -100  # 이미 오래 지속
        bot.last_potion_effective = False
        with patch_view({"hp": 0.4, "safe_zone": False, "_frame": None}):
            bot.step()
        self.assertEqual(bot.state, "RETREAT")

    def test_hunt_time_over_moves_next_ground(self):
        bot, win, _ = make_bot(hp=0.9)
        bot.state = "HUNT"
        bot.hunt_started = -100000
        with patch_view({"hp": 0.9, "safe_zone": False, "_frame": None}):
            bot.step()
        self.assertEqual(bot.state, "RETREAT")
        self.assertEqual(bot.ground_idx, 1)

    def test_retreat_home_then_supply_and_log(self):
        bot, win, _ = make_bot(hp=0.9)
        bot.state = "RETREAT"
        bot.hunt_started = -60
        import cycle_bot as cb, json
        with patch_view({"hp": 1.0, "safe_zone": True, "_frame": None}):
            bot.step()
        self.assertEqual(bot.state, "SUPPLY")
        line = json.loads(cb.LOG_PATH.read_text(encoding="utf-8").strip().splitlines()[-1])
        self.assertEqual(line["ground"], "A터")

    def test_recover_double_death_demotes_ground(self):
        bot, win, _ = make_bot(hp=0)
        bot.state = "RECOVER"
        with patch_view({"hp": 0, "safe_zone": False, "_frame": None}):
            bot.step()
            bot.state = "RECOVER"
            bot.step()
        self.assertEqual(bot.ground_idx, 1)

    def test_supply_reranks_grounds_from_log(self):
        """사냥 기록이 있으면 SUPPLY에서 우선순위가 재배열된다(설계 13번)."""
        import json, time
        from pathlib import Path
        log = Path(__file__).parent / "hunt_log.jsonl"
        keep = log.read_text(encoding="utf-8") if log.exists() else ""
        try:
            with log.open("a", encoding="utf-8") as sink:
                sink.write(json.dumps({"t": time.time(), "ground": "A터",
                                       "minutes": 60, "potions": 600,
                                       "death": True}) + "\n")
            bot, win, _ = make_bot(hp=1.0, safe=True)
            bot.state = "SUPPLY"
            with patch_view({"hp": 1.0, "safe_zone": True, "_frame": None}):
                bot.step()
            names = [g["name"] for g in bot.cfg["hunting_grounds"]]
            self.assertEqual(names[0], "B터")
        finally:
            if keep:
                log.write_text(keep, encoding="utf-8")
            elif log.exists():
                log.unlink()

    def test_travel_arrival_starts_hunt(self):
        bot, win, _ = make_bot(hp=1.0, safe=False)
        bot.state = "TRAVEL"
        with patch_view({"hp": 1.0, "safe_zone": False, "_frame": None}):
            bot.step()
        self.assertEqual(bot.state, "HUNT")
        self.assertGreater(bot.hunt_started, 0)


if __name__ == "__main__":
    unittest.main()
