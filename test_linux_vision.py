"""실물 판독 및 로그인/사망/지역 미확인 상태의 입력 차단을 검증한다."""
import os
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import linux_vision as vision


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((1332, 1933, 3), dtype=np.uint8)
        # HP는 실측 게이지/숫자 폴백이 실 픽셀을 보므로 mock으로 끊고
        # side_effect 시퀀스는 기존 텍스트 판독 순서를 유지한다.
        gauge_patcher = patch.object(vision, "hp_from_gauge", return_value=None)
        digits_patcher = patch.object(vision, "hp_from_hud_digits", return_value=None)
        gauge_patcher.start()
        digits_patcher.start()
        self.addCleanup(gauge_patcher.stop)
        self.addCleanup(digits_patcher.stop)

    def test_invalid_frame(self):
        self.assertFalse(vision.analyze(None)["ready"])
        self.assertFalse(vision.analyze(self.frame[:100])["ready"])
        resized = np.zeros((1374, 1933, 3), dtype=np.uint8)
        with patch.object(vision, "ocr") as reader:
            self.assertFalse(vision.analyze(resized)["ready"])
        reader.assert_not_called()

    def test_ratio_rejects_ambiguous_numbers(self):
        self.assertEqual(vision.parse_ratio("HP71/71", "HP"), 1)
        self.assertEqual(vision.parse_ratio("HP: 14/71", "HP"), 14 / 71)
        for value in ["HP7171", "HP71/0", "HP72/71", "71/71", "HP?1/71"]:
            self.assertIsNone(vision.parse_ratio(value, "HP"))

    def test_zone_kind_real_ocr_variants(self):
        for text in ["Safety zone", "Safety zoHe", "'; Satety zone'", "Satety zoHe",
                     "Safety cone", "satety zone", "safety z0ne"]:
            with self.subTest(text=text):
                self.assertEqual(vision.zone_kind(text), "safe")
        for text in ["Normal zone", "combat zone", "Normal cone"]:
            with self.subTest(text=text):
                self.assertEqual(vision.zone_kind(text), "combat")
        # 첫 단어가 깨지거나 다른 단어면 마을로 오인하지 않는다.
        for text in ["???", "Safy zone", "Sunny zone", "safe"]:
            with self.subTest(text=text):
                self.assertEqual(vision.zone_kind(text), "unknown")

    def test_game_visible_survives_zone_read_failure(self):
        """zone 판독 실패 중에도 이동 전용 입력은 게임 화면 확인으로 허용한다."""
        texts = ["purpleon.plaync.com/webplay/linclassic", "HP71/71", "MP7/7", "???"]
        with patch.object(vision, "ocr", side_effect=texts), \
                patch.object(vision, "zone_read", return_value="???"):
            result = vision.analyze(self.frame)
        self.assertFalse(result["ready"])
        self.assertTrue(result["game_visible"])

    def test_game_visible_false_when_dead_or_wrong_tab(self):
        for texts in [["purpleon.plaync.com/webplay/linclassic", "HP0/71", "MP7/7", "Normal zone"],
                      ["example.com", "HP71/71", "MP7/7", "Normal zone"],
                      ["purpleon.plaync.com/webplay/linclassic", "HP?1/71", "MP7/7", "Normal zone", "", ""]]:
            with self.subTest(texts=texts), \
                    patch.object(vision, "ocr", side_effect=texts), \
                    patch.object(vision, "zone_read", return_value="Normal zone"):
                result = vision.analyze(self.frame)
            self.assertFalse(result["game_visible"])

    def test_wrong_tab_blocks(self):
        with patch.object(vision, "ocr", return_value="example.com"):
            self.assertFalse(vision.analyze(self.frame)["ready"])

    def test_safety_zone_blocks_candidates(self):
        # zone_read는 다중 rect/잉크 가드를 쓰므로 값 자체를 패치해
        # analyze의 마을 게이트 동작만 검증한다(판독기 자체는 실물 프레임 검증).
        texts = ["purpleon.plaync.com/webplay/linclassic", "HP71/71", "MP7/7", ""]
        with patch.object(vision, "ocr", side_effect=texts), \
                patch.object(vision, "zone_read", return_value="Safety zoHe"):
            result = vision.analyze(self.frame)
        self.assertTrue(result["ready"])
        self.assertTrue(result["safe_zone"])
        self.assertEqual(result["mobs"], [])

    def test_death_and_unknown_zone_block(self):
        for hp, zone in [("HP0/71", "Normal zone"), ("HP71/71", "???")]:
            texts = ["purpleon.plaync.com/webplay/linclassic", hp, "MP7/7", ""]
            with patch.object(vision, "ocr", side_effect=texts), \
                    patch.object(vision, "zone_read", return_value=zone):
                self.assertFalse(vision.analyze(self.frame)["ready"])

    def test_hud_and_health_bars_are_not_monsters(self):
        cv2.rectangle(self.frame, (800, 1045), (1100, 1070), (0, 0, 255), -1)
        cv2.rectangle(self.frame, (1160, 510), (1230, 516), (0, 0, 255), -1)
        cv2.putText(self.frame, "RED CHAT", (900, 1150), cv2.FONT_HERSHEY_SIMPLEX,
                    1, (0, 0, 255), 2)
        self.assertEqual(vision.red_name_candidates(self.frame), [])

    def test_red_name_is_not_automatically_a_monster(self):
        cv2.putText(self.frame, "RED NAME", (800, 400), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (0, 0, 255), 1)
        self.assertTrue(vision.red_name_candidates(self.frame))
        texts = ["purpleon.plaync.com/webplay/linclassic", "HP71/71", "MP7/7", "Normal zone", ""]
        with patch.object(vision, "ocr", side_effect=texts):
            result = vision.analyze(self.frame)
        self.assertEqual(result["mobs"], [])

    def test_menu_close_blocks_even_when_hp_and_zone_are_readable(self):
        texts = ["purpleon.plaync.com/webplay/linclassic", "HP71/71", "MP7/7", "Close"]
        with patch.object(vision, "ocr", side_effect=texts), \
                patch.object(vision, "zone_read", return_value="Normal zone"):
            result = vision.analyze(self.frame)
        self.assertFalse(result["ready"])
        self.assertIn("패널", result["reason"])
        self.assertEqual(result["mobs"], [])

    def test_inventory_grid_blocks_without_close_text(self):
        x, y, width, height = vision.INVENTORY_GRID_RECT
        for offset in [10, 80, 150, 220, 290]:
            cv2.line(self.frame, (x + offset, y), (x + offset, y + height - 1),
                     (180, 180, 180), 2)
        for offset in range(0, 565, 70):
            cv2.line(self.frame, (x, y + offset), (x + width - 1, y + offset),
                     (180, 180, 180), 2)
        with patch.object(vision, "ocr") as reader:
            self.assertTrue(vision.panel_visible(self.frame))
        reader.assert_not_called()

    def test_verified_profile_uses_body_offset_and_rejects_invalid_targets(self):
        profiles = {"검증몹": (4, 33), "잘못된프로필": "33", "이름만등록": None,
                    "이름표중앙": (0, 0), "소수좌표": (0, 2.5)}
        with patch.object(vision, "VERIFIED_TARGET_PROFILES", profiles):
            self.assertEqual(vision.body_target("검증몹", 800, 400), (804, 433))
            self.assertIsNone(vision.body_target("검증몹", 800, 950))
            for name in ["미등록몹", "잘못된프로필", "이름만등록", "이름표중앙", "소수좌표"]:
                self.assertIsNone(vision.body_target(name, 800, 400))

    def test_analyze_returns_body_not_name_center(self):
        cv2.putText(self.frame, "RED NAME", (800, 400), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (0, 0, 255), 1)
        candidates = vision.red_name_candidates(self.frame)
        texts = ["purpleon.plaync.com/webplay/linclassic", "HP71/71", "MP7/7", ""]
        texts += ["검증몹"] * len(candidates)
        with patch.object(vision, "ocr", side_effect=texts), \
                patch.object(vision, "zone_read", return_value="Normal zone"):
            result = vision.analyze(self.frame, target_profiles={"검증 몹": [4, 33]})
        self.assertEqual(result["mobs"], [(x + 4, y + 33, area)
                                          for x, y, area, _ in candidates])

    def test_profile_validator_rejects_invalid_json_data_immediately(self):
        for profiles in [None, [], "몹", {"": [0, 20]}, {"몹": [0, 0]},
                         {"몹": [0, True]}, {"몹": [0, 2.5]}, {"몹": [0]},
                         {"몹": "20"}, {"몹": [0, 10000]}, {1: [0, 20]},
                         {"검증 몹": [0, 20], "검증몹": [0, 30]}]:
            with self.subTest(profiles=profiles), self.assertRaises(ValueError):
                vision.validate_target_profiles(profiles)
        with self.assertRaises(ValueError):
            vision.analyze(None, target_profiles={"몹": None})
        self.assertEqual(vision.validate_target_profiles({"검증 몹": [2, 30]}),
                         {"검증몹": (2, 30)})
        self.assertEqual(vision.validate_target_profiles({}), {})

    def test_empty_injected_profiles_override_global_defaults(self):
        cv2.putText(self.frame, "RED NAME", (800, 400), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (0, 0, 255), 1)
        texts = ["purpleon.plaync.com/webplay/linclassic", "HP71/71", "MP7/7", "Normal zone", ""]
        with patch.object(vision, "VERIFIED_TARGET_PROFILES", {"검증몹": (4, 33)}), \
                patch.object(vision, "ocr", side_effect=texts):
            result = vision.analyze(self.frame, target_profiles={})
        self.assertEqual(result["mobs"], [])

    @unittest.skipUnless(os.path.exists("/tmp/linc-bot-linux-move2/0000-before.png"),
                         "인벤토리 실물 캡처 없음")
    def test_captured_inventory_blocks(self):
        frame = cv2.imread("/tmp/linc-bot-linux-move2/0000-before.png")
        self.assertTrue(vision.inventory_grid_visible(frame))
        result = vision.analyze(frame)
        # HP 좌표는 CDP 창 실측(2026-09-07)으로 갱신돼 구 캡처에선 HP 실패로
        # 먼저 차단될 수 있다. 어느 쪽이든 입력 차단이면 취지 충족이다.
        self.assertFalse(result["ready"], result)
        self.assertIn("차단", result["reason"])
        self.assertEqual(result["mobs"], [])

    @unittest.skipUnless(os.path.exists("/tmp/purpleon-window.png"), "실물 캡처 없음")
    def test_captured_purpleon(self):
        result = vision.analyze(cv2.imread("/tmp/purpleon-window.png"))
        # 구 X11 캡처: 캘리브레이션 갱신 후엔 몹 후보만 검증한다.
        self.assertEqual(result["mobs"], [])
class ZoneAndOcrGuardTests(VisionTests):
    """재리뷰 지적(리그레션 미고정) 반영 — zone 원값/OCR None 방어."""

    def test_analyze_exposes_raw_zone_value(self):
        """zone 원값(safe/combat/unknown)을 노출해 실패와 필드를 구분한다."""
        for zone_text, expected in [("Safety zone", "safe"),
                                    ("Normal zone", "combat"),
                                    ("???", "unknown")]:
            with (self.subTest(zone=zone_text),
                  patch.object(vision, "ocr", side_effect=[
                      "purpleon.plaync.com/webplay/linclassic", "HP71/71",
                      "MP7/7", ""]),
                  patch.object(vision, "zone_read", return_value=zone_text)):
                result = vision.analyze(self.frame)
            self.assertEqual(result["zone"], expected)

    def test_zone_default_is_unknown_before_reading(self):
        """판독 실패 경로에서도 zone은 unknown으로 내려온다(기본값)."""
        self.assertEqual(vision.analyze(self.frame)["zone"], "unknown")

    def test_hud_digits_ocr_none_is_not_a_crash(self):
        """OCR이 None을 반환해도 크래시 없이 None 비율을 낸다."""
        with patch.object(vision, "ocr", return_value=None):
            self.assertIsNone(vision.hp_from_hud_digits(self.frame))


if __name__ == "__main__":
    unittest.main()
