"""실물 판독 및 로그인/사망/지역 미확인 상태의 입력 차단을 검증한다."""
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _gauge_frame(bar_w, bar_h=29, hl_w=232, hl_h=6):
    """HP_GAUGE_BAND에 진짜 막대(h29) + 테두리 하이라이트(h6)를 그은 합성 프레임.

    위치/높이는 fixture 실측(2026-09-13): 막대 (x57,y60,h29),
    하이라이트 (x59,y53,h6). BGR(60,60,200)은 게이지 빨강 마스크를
    통과하는 색이라 성분 검출 경로가 실제와 같다.
    """
    img = np.zeros((1332, 1933, 3), np.uint8)
    bx, by, _, _ = vision.HP_GAUGE_BAND
    if bar_w > 0:
        img[by + 60:by + 60 + bar_h, bx + 57:bx + 57 + bar_w] = (60, 60, 200)
    if hl_w > 0:
        img[by + 53:by + 53 + hl_h, bx + 59:bx + 59 + hl_w] = (60, 60, 190)
    return img


class TestHpGaugeSynthetic(unittest.TestCase):
    """hp_from_gauge 합성 회귀 (BTS-1033250 — 트랙 334px 기준)."""

    def setUp(self):
        vision._LAST_HP = None
        vision._LAST_HP_TS = 0.0
        vision._LAST_MAX = None
        vision._LAST_RECT_IDX = 0

    def test_풀막대는_1점을_내놓는다(self):
        self.assertAlmostEqual(vision.hp_from_gauge(_gauge_frame(334)),
                               1.0, delta=0.02)

    def test_반막대는_0점5를_내놓는다(self):
        self.assertAlmostEqual(vision.hp_from_gauge(_gauge_frame(167)),
                               0.50, delta=0.02)

    def test_막대_없으면_하이라이트만_으로는_None이다(self):
        # HP와 무관한 6px 테두리 하이라이트(w232)를 막대로 오인하면
        # 232/334=0.695를 반환 → 물약 임계 근처 고착(종전 버그 재발).
        self.assertIsNone(vision.hp_from_gauge(_gauge_frame(0)))

    def test_HUD_글자로_끊긴_막대는_이어붙여_잰다(self):
        # 실화면(2026-09-13 사막던전4층, HP 247/253)은 막대 위에 겹쳐 쓴
        # `HP : 247/253` 글자가 빨간 채움을 끊어 조각(12~197 / 219~346,
        # 최대 갭 37px)을 만든다. 가장 넓은 조각만 재면 244/334=0.73으로
        # 읽어 만피인데 물약을 계속 먹는다. 글자 폭 갭은 이어붙여야 한다.
        img = _gauge_frame(190)
        bx, by, _, _ = vision.HP_GAUGE_BAND
        img[by + 60:by + 89, bx + 57 + 190 + 37:bx + 57 + 330] = (60, 60, 200)
        self.assertAlmostEqual(vision.hp_from_gauge(img), 1.0, delta=0.02)

    def test_멀리_떨어진_빨강은_막대로_이어붙이지_않는다(self):
        # 갭 상한을 넘는 빨간 장식까지 이으면 저피를 만피로 읽어
        # 물약을 안 먹고 죽는다(가장 위험한 방향).
        img = _gauge_frame(150)
        bx, by, _, _ = vision.HP_GAUGE_BAND
        img[by + 60:by + 89, bx + 57 + 150 + 90:bx + 57 + 330] = (60, 60, 200)
        self.assertAlmostEqual(vision.hp_from_gauge(img), 150 / 334,
                               delta=0.02)

    def test_HP_낮을때_하이라이트가_더_넓어도_막대_폭을_잰다(self):
        # 막대 150px(HP 45%) vs 하이라이트 232px: '가장 넓은 성분'을 고르면
        # 하이라이트가 이겨 0.695로 옮겨 붙는다. 진짜 막대 폭을 봐야 한다.
        self.assertAlmostEqual(vision.hp_from_gauge(_gauge_frame(150)),
                               150 / 334, delta=0.02)


class TestHpGaugeFixture(unittest.TestCase):
    """실측 프레임 고정 회귀 — HP 202/244(만피 아님) fixtures/hp_202_244.png.

    만피 프레임으로는 이 버그를 못 잡는다(하이라이트도 풀폭이라).
    """

    @classmethod
    def setUpClass(cls):
        cls.frame = cv2.imread(str(FIXTURES / "hp_202_244.png"))
        assert cls.frame is not None, "fixtures/hp_202_244.png 없음"
        assert cls.frame.shape[:2] == (1332, 1933), cls.frame.shape

    def setUp(self):
        vision._LAST_HP = None
        vision._LAST_HP_TS = 0.0
        vision._LAST_MAX = None
        vision._LAST_RECT_IDX = 0

    def test_게이지가_OCR과_일치한다(self):
        # 종전 오판독: 풀피를 0.7036으로 읽어 물약 무한 소모.
        self.assertAlmostEqual(vision.hp_from_gauge(self.frame),
                               202 / 244, delta=0.02)

    def test_hp_read가_OCR_정밀값을_낸다(self):
        self.assertAlmostEqual(vision.hp_read(self.frame),
                               202 / 244, delta=0.01)


class TestHpRead(unittest.TestCase):
    """hp_read 통합 판독 (BTS-1033250 — 게이지 height 필터 수정 후 스펙)."""

    def setUp(self):
        vision._LAST_HP = None
        vision._LAST_HP_TS = 0.0
        self.img = object()

    def _patch(self, ocr, gauge=None):
        gauge_mock = (Mock(side_effect=gauge) if isinstance(gauge, list)
                      else Mock(return_value=gauge))
        return patch.multiple(
            vision,
            hp_from_hud_digits=Mock(side_effect=ocr),
            hp_from_gauge=gauge_mock,
        )

    def test_ocr와_게이지가_일치하면_ocr_정밀값을_쓴다(self):
        # OCR 206/244=0.844 vs 게이지 279/334=0.835 — 정상 프레임.
        with self._patch([0.844], gauge=0.835):
            self.assertAlmostEqual(vision.hp_read(self.img), 0.844)

    def test_ocr_오독_급락은_게이지로_교정한다(self):
        # 라이브 실측: 206/244가 한 프레임 20/244(0.083)로 오독 — 게이지
        # 0.83과 0.75 벌어짐. 0.083을 그대로 반환하면 물약 연타/귀환 사고.
        with self._patch([0.844, 0.083], gauge=0.83):
            self.assertAlmostEqual(vision.hp_read(self.img), 0.844)
            self.assertAlmostEqual(vision.hp_read(self.img), 0.83)

    def test_ocr_실패시_게이지로_폴백한다(self):
        # 게이지는 height 필터 수정(2026-09-13 실측)으로 신뢰 회복.
        with self._patch([None], gauge=0.83):
            self.assertAlmostEqual(vision.hp_read(self.img), 0.83)

    def test_둘다_실패시_최근값을_짧게_유지한다(self):
        with self._patch([0.93, None], gauge=None):
            self.assertAlmostEqual(vision.hp_read(self.img), 0.93)
            self.assertAlmostEqual(vision.hp_read(self.img), 0.93)

    def test_오래된_값은_버리고_모른다고_답한다(self):
        with self._patch([0.93, None], gauge=None):
            vision.hp_read(self.img)
            vision._LAST_HP_TS -= vision.HP_STALE_SEC + 1
            self.assertIsNone(vision.hp_read(self.img))

    def test_진짜_급락은_두번째_프레임에_채택한다(self):
        # 게이지가 HP를 따라 내려오는(=진짜) 급락: 1프레임 유보 후 채택.
        with self._patch([0.9, 0.13, 0.13], gauge=[0.88, 0.15, 0.15]):
            self.assertAlmostEqual(vision.hp_read(self.img), 0.9)
            self.assertAlmostEqual(vision.hp_read(self.img), 0.9)
            self.assertAlmostEqual(vision.hp_read(self.img), 0.13)


class TestHpDynamicTextRect(unittest.TestCase):
    """BTS-1033467: 막대 y 앵커 동적 rect — 고정 rect 시프트 전멸 대응.

    재접속마다 HUD가 시프트해 고정 HP_CUR/MAX/PAIR 후보가 전멸했다.
    find_hp_text_rect()가 두 실측 레이아웃(2026-09-13/09-15)에서 각기
    다른 y를 정확히 찾아 'nnn/nnn' 판독에 성공해야 한다.
    """

    def _check(self, fixture, expected_low, expected_high):
        img = cv2.imread(str(FIXTURES / fixture))
        self.assertIsNotNone(img, f"{fixture} 없음")
        vision._LAST_MAX = None
        vision._LAST_RECT_IDX = 0
        rect = vision.find_hp_text_rect(img)
        self.assertIsNotNone(rect, f"{fixture}: 동적 rect 미탐지")
        text = vision.ocr(vision.crop(img, rect), whitelist="0123456789/")
        cs, ms = text.strip().split("/")
        self.assertEqual(int(cs), expected_low, f"{fixture}: {text!r}")
        self.assertEqual(int(ms), expected_high, f"{fixture}: {text!r}")

    def test_0913_레이아웃(self):
        self._check("hp_202_244.png", 202, 244)

    def test_0915_시프트_레이아웃(self):
        self._check("hp_2026-09-15_shift.png", 238, 263)

    def test_동적_rect_실패시_hp_from_hud_digits는_고정_후보로_폴백(self):
        # 막대가 없는(검은) 프레임에서는 동적 rect가 None이어야 하고,
        # hp_from_hud_digits가 고정 후보 경로를 그대로 탄다(예외 없이 None).
        import numpy as np
        blank = np.zeros((1332, 1933, 3), dtype=np.uint8)
        self.assertIsNone(vision.find_hp_text_rect(blank))
        vision._LAST_MAX = None
        self.assertIsNone(vision.hp_from_hud_digits(blank))


class TestHpDenominatorGuard(unittest.TestCase):
    """분모(최대 HP) 점프 오독 가드 (BTS-1033250)."""

    def setUp(self):
        vision._LAST_MAX = None
        vision._LAST_RECT_IDX = 0
        self.frame = np.zeros((1332, 1933, 3), np.uint8)

    def _ocr(self, texts):
        return patch.object(vision, "ocr", side_effect=texts)

    def test_분모_점프_프레임은_유보하고_복귀후_승인한다(self):
        # max가 증가 방향으로 오독(244→344)되면 low<=high 검증을 통과해
        # 205/344=0.596으로 급락 — 분모가드가 1프레임 유보로 막는다.
        # 감소 방향(244→24)은 low<=high에서 이미 차단된다(별도 테스트).
        with self._ocr(["206", "244",
                        "205", "344",
                        "204", "244",
                        "203", "244"]):
            self.assertAlmostEqual(vision.hp_from_hud_digits(self.frame),
                                   206 / 244)
            self.assertIsNone(vision.hp_from_hud_digits(self.frame))
            self.assertIsNone(vision.hp_from_hud_digits(self.frame))
            self.assertAlmostEqual(vision.hp_from_hud_digits(self.frame),
                                   203 / 244)

    def test_분모_감소_오독은_low_le_high_검증이_차단한다(self):
        # max 244→24 오독: current(205) > maximum(24)라 기존 검증에서 후보
        # 탈락(후보를 1개로 고정해 순차 시도 효과를 제거하고 검증).
        with self._ocr(["206", "244", "205", "24", "204", "244"]), \
                patch.object(vision, "HP_CUR_RECTS", vision.HP_CUR_RECTS[:1]), \
                patch.object(vision, "HP_MAX_RECTS", vision.HP_MAX_RECTS[:1]), \
                patch.object(vision, "HP_PAIR_RECTS", ()):  # 분리경로만 검증
            self.assertAlmostEqual(vision.hp_from_hud_digits(self.frame),
                                   206 / 244)
            self.assertIsNone(vision.hp_from_hud_digits(self.frame))
            self.assertAlmostEqual(vision.hp_from_hud_digits(self.frame),
                                   204 / 244)

    def test_후보_rect를_순차_시도해_시프트를_흡수한다(self):
        # 후보0(구 레이아웃)이 빈 문자열 → 후보1(2026-09-13 시프트) 채택.
        with self._ocr(["", "", "253", "253"]):
            self.assertAlmostEqual(vision.hp_from_hud_digits(self.frame), 1.0)
            self.assertEqual(vision._LAST_RECT_IDX, 1)
        # 다음 프레임은 최근 성공 후보(1)부터 — 후보0을 건너뛴다.
        with self._ocr(["253", "253"]):
            self.assertAlmostEqual(vision.hp_from_hud_digits(self.frame), 1.0)

    def test_형식_오독_후보는_건너뛰고_다음_후보를_시도한다(self):
        # 후보0이 low>high(205/24) 형식 오독 → 프레임을 버리지 않고
        # 후보1로 넘어가 247/253을 채택한다. '형식 거부'와 '분모 유보'를
        # 섞으면 이 프레임이 통째로 None이 되므로 회귀 감시용.
        with self._ocr(["205", "24", "247", "253"]):
            self.assertAlmostEqual(vision.hp_from_hud_digits(self.frame),
                                   247 / 253)
            self.assertEqual(vision._LAST_RECT_IDX, 1)

    def test_분리크롭_전멸시_합본rect가_슬래시로_복구한다(self):
        # 실측(2026-09-13 사막던전4층 /tmp/hunt_now.png): 글자 시프트로
        # 분리 크롭 후보 2개가 모두 빈 문자열을 돌려 전멸했고, 합본
        # rect만 'HP : 247/253'을 정확히 읽었다.
        with self._ocr(["", "", "", "", "247/253"]):
            self.assertAlmostEqual(vision.hp_from_hud_digits(self.frame),
                                   247 / 253)

    def test_합본rect도_실패하면_None으로_게이지폭에_넘긴다(self):
        # 합본이 슬래시 0개/2개로 깨지면 채택하지 않는다(오독 주입 방지).
        with self._ocr(["", "", "", "", "", "247253", "247/25/3", ""]):
            self.assertIsNone(vision.hp_from_hud_digits(self.frame))

    def test_레벨업_분모_변경은_다음_프레임에_승인한다(self):
        with self._ocr(["206", "244", "205", "260", "250", "260"]):
            self.assertAlmostEqual(vision.hp_from_hud_digits(self.frame),
                                   206 / 244)
            self.assertIsNone(vision.hp_from_hud_digits(self.frame))
            self.assertAlmostEqual(vision.hp_from_hud_digits(self.frame),
                                   250 / 260)


if __name__ == "__main__":
    unittest.main()


class HpGaugeStrayRedTest(unittest.TestCase):
    """BTS-1033358: 막대 밖 빨강에 판독이 끌려가지 않는지."""

    def setUp(self):
        vision._LAST_HP = None
        vision._LAST_HP_TS = 0.0
        vision._RECOVERY_UNTIL = 0.0

    @staticmethod
    def _with_stray(bar_w, offsets, stray_h, stray_w=10):
        """막대 오른쪽 offsets 위치에 빨간 조각을 덧그린 프레임."""
        img = _gauge_frame(bar_w)
        bx, by, _, _ = vision.HP_GAUGE_BAND
        for off in offsets:
            x = bx + 57 + bar_w + off
            img[by + 60:by + 60 + stray_h, x:x + stray_w] = (60, 60, 200)
        return img

    def test_얇은_막대밖_빨강은_이어붙이지_않는다(self):
        # 이름표/데미지 숫자처럼 얇은(10/29행) 빨강. 종전 need=bh*0.25(7행)
        # 은 이걸 채움으로 오인해 막대 밖으로 끌려갔다.
        img = self._with_stray(150, [20], stray_h=10)
        self.assertAlmostEqual(vision.hp_from_gauge(img), 150 / 334, places=3)

    def test_갭_이어붙이기는_연쇄되지_않는다(self):
        # 채움 높이 빨강이 GAP_TOL 간격으로 늘어서 있어도 한 번만 잇는다.
        # 종전 while 루프는 hop을 연쇄해 맨 끝까지 끌려갔다.
        img = self._with_stray(150, [30, 70, 110], stray_h=29)
        got = vision.hp_from_gauge(img)
        self.assertAlmostEqual(got, (150 + 30 + 10) / 334, places=3)
        self.assertLess(got, (150 + 110) / 334)

    def test_글자_갭은_여전히_이어붙인다(self):
        # 회귀 방지: 실측 37px 글자 갭 건너편 채움(h29)은 반드시 이어야 한다.
        img = self._with_stray(150, [37], stray_h=29, stray_w=60)
        self.assertAlmostEqual(vision.hp_from_gauge(img),
                               (150 + 37 + 60) / 334, places=3)


class HpRiseGuardTest(unittest.TestCase):
    """BTS-1033358: 회복 없는 HP 급상승 유보."""

    def setUp(self):
        vision._LAST_HP = None
        vision._LAST_HP_TS = 0.0
        vision._RECOVERY_UNTIL = 0.0
        digits = patch.object(vision, "hp_from_hud_digits", return_value=None)
        digits.start()
        self.addCleanup(digits.stop)

    def test_회복_없는_급상승은_한_프레임_유보된다(self):
        with patch.object(vision, "hp_from_gauge",
                          side_effect=[0.754, 0.874, 0.874]) as g:
            frame = object()
            self.assertAlmostEqual(vision.hp_read(frame), 0.754)
            # 라이브 실측 오독(+0.12)은 즉시 채택되지 않는다.
            self.assertAlmostEqual(vision.hp_read(frame), 0.754)
            # 다음 프레임에 같은 값이 또 나오면 채택한다(고착 없음).
            self.assertAlmostEqual(vision.hp_read(frame), 0.874)
            self.assertEqual(g.call_count, 3)

    def test_물약_직후_상승은_즉시_채택된다(self):
        with patch.object(vision, "hp_from_gauge", side_effect=[0.754, 0.98]):
            frame = object()
            self.assertAlmostEqual(vision.hp_read(frame), 0.754)
            vision.note_recovery(5.0)
            self.assertAlmostEqual(vision.hp_read(frame), 0.98)
