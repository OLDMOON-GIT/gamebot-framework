"""바닥 아이템 라벨 검출 검증 (SPEC-1032722).

실측 캡처에는 드랍이 찍힌 positive 샘플이 없어 실물로는 오탐(false positive)만
검증 가능하다. 검출 성공 경로는 라벨과 같은 형태(흰 테두리 사각형)를 합성해
확인한다.
"""
import glob
import os
import unittest

import cv2
import numpy as np

import item_labels as il


def draw_label(img, x, y, w, h):
    """실제 드랍 라벨 형태(흰 테두리 + 내부 어두운 글씨)를 그린다."""
    cv2.rectangle(img, (x, y), (x + w, y + h), (235, 235, 235), 2)
    cv2.rectangle(img, (x + 2, y + 2), (x + w - 2, y + h - 2), (40, 40, 40), -1)


def blank(h=1332, w=1933, v=60):
    return np.full((h, w, 3), v, dtype=np.uint8)


class DetectTests(unittest.TestCase):
    def test_single_label_geometry(self):
        """라벨 하나의 중심/하단/크기를 픽셀 단위로 맞게 잡는다."""
        img = blank()
        draw_label(img, 1100, 620, 90, 26)
        labels = il.detect_labels(img, il.PICK_RECT)

        self.assertEqual(len(labels), 1)
        lb = labels[0]
        self.assertAlmostEqual(lb.cx, 1100 + 90 // 2, delta=8)
        self.assertAlmostEqual(lb.bottom, 620 + 26, delta=4)
        self.assertAlmostEqual(lb.h, 26, delta=4)

    def test_click_is_below_label(self):
        """클릭점은 라벨 하단 살짝 아래 = 아이템 실제 위치.

        기대값을 리터럴로 박아 PICK_DY 가 흔들리면 반드시 실패하게 한다
        (il.PICK_DY 로 쓰면 어떤 값이든 통과하는 동어반복이 된다).
        """
        img = blank()
        draw_label(img, 900, 500, 120, 28)
        lb = il.detect_labels(img, il.PICK_RECT)[0]

        self.assertEqual(lb.click, (lb.cx, lb.bottom + 18))
        # 아이템 스프라이트는 라벨 바로 아래 한 칸 안에 있다
        self.assertTrue(0 < lb.click[1] - lb.bottom <= 32)

    def test_multiple_labels_sorted_top_to_bottom(self):
        img = blank()
        draw_label(img, 1240, 700, 140, 30)
        draw_label(img, 1100, 620, 90, 26)
        labels = il.detect_labels(img, il.PICK_RECT)

        self.assertEqual(len(labels), 2)
        self.assertEqual([l.bottom for l in labels],
                         sorted(l.bottom for l in labels))

    def test_empty_background_detects_nothing(self):
        self.assertEqual(il.detect_labels(blank(), il.PICK_RECT), [])

    def test_noise_background_detects_nothing(self):
        """밝은 점 노이즈는 수평선이 아니므로 라벨이 아니다."""
        rng = np.random.default_rng(0)
        img = rng.integers(0, 256, (1332, 1933, 3), dtype=np.uint8)
        self.assertEqual(il.detect_labels(img, il.PICK_RECT), [])

    def test_label_outside_roi_ignored(self):
        """ROI 밖(우측 스킬바 영역)의 라벨은 무시한다."""
        img = blank()
        draw_label(img, il.PICK_RECT[2] + 20, 600, 90, 26)
        self.assertEqual(il.detect_labels(img, il.PICK_RECT), [])

    def test_too_narrow_and_too_wide_ignored(self):
        for w in (il.MIN_W - 15, il.MAX_W + 40):
            with self.subTest(w=w):
                img = blank()
                draw_label(img, 800, 600, w, 26)
                self.assertEqual(il.detect_labels(img, il.PICK_RECT), [])

    def test_too_short_and_too_tall_ignored(self):
        """세로 간격이 라벨 범위를 벗어나면(가로줄 UI 등) 무시한다."""
        for h in (il.MIN_H - 10, il.MAX_H + 20):
            with self.subTest(h=h):
                img = blank()
                draw_label(img, 800, 500, 90, h)
                self.assertEqual(il.detect_labels(img, il.PICK_RECT), [])

    def test_annotate_does_not_mutate_input(self):
        img = blank()
        draw_label(img, 1100, 620, 90, 26)
        before = img.copy()
        il.annotate(img, il.detect_labels(img, il.PICK_RECT))
        self.assertTrue(np.array_equal(img, before))


class RealCaptureTests(unittest.TestCase):
    """실물 캡처 오탐 검증. 드랍이 없는 화면에서 0이어야 한다."""

    # 같은 파일이 두 패턴에 걸려 중복되던 것을 set 으로 제거하고, 디렉터리의
    # 캡처 전체를 검증 대상으로 삼는다(실측 43장).
    SHOTS = sorted(set(glob.glob("/tmp/linc-bot-linux/*.png")))

    @unittest.skipUnless(SHOTS, "실물 캡처 없음")
    def test_no_false_positive_on_dropless_shots(self):
        for path in self.SHOTS:
            with self.subTest(shot=os.path.basename(path)):
                img = cv2.imread(path)
                if img is None:
                    self.skipTest(f"읽기 실패: {path}")
                labels = il.detect_labels(img, il.PICK_RECT)
                self.assertEqual(labels, [], f"{path} 에서 오탐 {len(labels)}건")

    @unittest.skipUnless(SHOTS, "실물 캡처 없음")
    def test_synthetic_label_on_real_background(self):
        """실제 게임 배경(수풀/나무) 위에서도 라벨을 잡는다."""
        img = cv2.imread(self.SHOTS[0])
        if img is None:
            self.skipTest("읽기 실패")
        draw_label(img, 1100, 620, 90, 26)
        labels = il.detect_labels(img, il.PICK_RECT)
        self.assertEqual(len(labels), 1)


class BrokenBorderTests(unittest.TestCase):
    """어두운 배경에서 상단 테두리가 끊겨도 검출된다.

    실측(아데나 라벨): 하단선 135px 온전, 상단선 54px만 임계값 통과 →
    상/하단 폭 일치를 요구하던 기존 로직이 놓쳤다.
    """

    def _broken(self, top_w):
        img = blank()
        x, y, w, h = 1584, 427, 135, 38
        # 하단선만 온전, 상단선은 일부 구간만 밝게
        cv2.line(img, (x, y + h), (x + w, y + h), (235, 235, 235), 2)
        cv2.line(img, (x, y), (x + top_w, y), (235, 235, 235), 2)
        return img, x, y, w, h

    def test_detects_label_with_partial_top_border(self):
        img, x, y, w, h = self._broken(54)
        labels = il.detect_labels(img, il.PICK_RECT)

        self.assertEqual(len(labels), 1, "끊긴 상단선 라벨을 놓쳤다")
        lb = labels[0]
        # 폭은 끊긴 상단선(54)이 아니라 온전한 하단선(135) 기준이어야 한다
        self.assertAlmostEqual(lb.w, w, delta=6)
        self.assertAlmostEqual(lb.cx, x + w // 2, delta=8)
        self.assertAlmostEqual(lb.bottom, y + h, delta=4)

    def test_no_duplicate_when_top_border_fragmented(self):
        """상단선이 여러 조각이어도 라벨은 하나만 만든다."""
        img, x, y, w, h = self._broken(54)
        cv2.line(img, (x + 70, y), (x + 70 + 40, y), (235, 235, 235), 2)
        labels = il.detect_labels(img, il.PICK_RECT)
        self.assertEqual(len(labels), 1, f"중복 검출 {len(labels)}건")

    def test_unrelated_lines_do_not_pair(self):
        """멀리 떨어진 짧은 선은 같은 라벨로 묶이지 않는다."""
        img = blank()
        cv2.line(img, (1584, 465), (1584 + 135, 465), (235, 235, 235), 2)
        cv2.line(img, (1300, 427), (1300 + 50, 427), (235, 235, 235), 2)
        self.assertEqual(il.detect_labels(img, il.PICK_RECT), [])

    def _shifted_top(self, shift):
        """하단선 135px 고정, 상단선 54px 를 오른쪽으로 shift 만큼 민다."""
        img = blank()
        x, y, w, h = 1584, 427, 135, 38
        cv2.line(img, (x, y + h), (x + w, y + h), (235, 235, 235), 2)
        cv2.line(img, (x + shift, y), (x + shift + 54, y), (235, 235, 235), 2)
        return img

    def test_contain_min_boundary(self):
        """CONTAIN_MIN(0.8) 을 핀으로 고정한다.

        이 값이 없으면 0.0~1.0 어떤 값으로 바꿔도 전 테스트가 통과해버린다.
        겹침 0.81 은 통과, 0.63 은 탈락해야 한다.
        """
        self.assertEqual(len(il.detect_labels(self._shifted_top(91),
                                              il.PICK_RECT)), 1,
                         "겹침 81% 는 같은 라벨로 봐야 한다")
        self.assertEqual(il.detect_labels(self._shifted_top(100),
                                          il.PICK_RECT), [],
                         "겹침 63% 는 쌍이 되면 안 된다")


class StackedLabelTests(unittest.TestCase):
    """같은 x 에 세로로 쌓인 드랍(몹 하나가 여러 개 드랍) 처리.

    위 라벨의 하단선이 아래 라벨의 상단선과 짝지어지면 두 라벨 사이 빈
    공간에 유령 라벨이 생기고, 가장 먼 선을 먼저 잡으면 클릭 y 가 아래
    라벨 본체로 밀린다. 둘 다 실측으로 재현됐던 회귀다.
    """

    def test_no_phantom_between_stacked_labels(self):
        for gap in (4, 14, 20, 30, 40):
            with self.subTest(gap=gap):
                img = blank()
                y1 = 600
                y2 = y1 + 26 + gap
                draw_label(img, 1100, y1, 90, 26)
                draw_label(img, 1100, y2, 90, 26)
                labels = il.detect_labels(img, il.PICK_RECT)

                self.assertEqual(len(labels), 2,
                                 f"gap={gap} 검출 {len(labels)}건 "
                                 f"(bottoms={[l.bottom for l in labels]})")
                # 각 라벨의 하단이 자기 박스 하단과 맞아야 한다
                self.assertAlmostEqual(labels[0].bottom, y1 + 26, delta=4)
                self.assertAlmostEqual(labels[1].bottom, y2 + 26, delta=4)

    def test_stacked_bottom_not_dragged_downward(self):
        """각 라벨의 bottom 이 아래 라벨 쪽으로 끌려가지 않는다.

        정렬 없이 첫 매치를 확정하던 시절엔 가장 먼 선을 잡아 bottom 이
        최대 14px 밀렸다(실측 bottoms=[639,665], 정답 [625,665]).

        참고로 gap < PICK_DY(18) 이면 위 라벨의 클릭점이 아래 라벨 박스에
        들어가는데, 이는 매칭 버그가 아니라 오프셋의 구조적 한계다. 아래
        아이템을 먼저 줍게 될 뿐이고 aden_picker 도 아래부터 집는다.
        """
        img = blank()
        draw_label(img, 1100, 600, 90, 26)
        draw_label(img, 1100, 640, 90, 26)   # gap 14
        labels = il.detect_labels(img, il.PICK_RECT)

        self.assertEqual(len(labels), 2)
        self.assertAlmostEqual(labels[0].bottom, 626, delta=4,
                               msg=f"bottoms={[l.bottom for l in labels]}")
        self.assertAlmostEqual(labels[1].bottom, 666, delta=4)
        # 각 라벨 높이가 자기 박스 높이(26)여야 한다 — 이웃 선과 짝지으면 커진다
        for lb in labels:
            self.assertAlmostEqual(lb.h, 26, delta=4)


class LineSanityTests(unittest.TestCase):
    def test_single_line_alone_is_not_label(self):
        """상단선만 또는 하단선만 있으면 라벨이 아니다."""
        for name, y in (("상단선만", 600), ("하단선만", 626)):
            with self.subTest(case=name):
                img = blank()
                cv2.line(img, (1100, y), (1100 + 90, y), (235, 235, 235), 2)
                self.assertEqual(il.detect_labels(img, il.PICK_RECT), [])

    def test_extreme_width_ratio_does_not_pair(self):
        """40px 잡선이 무관한 240px 선과 묶여 중심이 밀리면 안 된다.

        포함 비율만 보던 시절 실측: click x 가 실제 라벨 중심에서 99px 어긋났다.
        """
        img = blank()
        # 두 선 모두 MIN_W~MAX_W 안에 들어야 한다. 238px 는 검출 폭이 241 이 돼
        # MAX_W(240) 에 먼저 걸리는 바람에 비율 가드를 전혀 타지 않았다.
        cv2.line(img, (900, 617), (900 + 200, 617), (235, 235, 235), 2)
        cv2.line(img, (1050, 591), (1050 + 45, 591), (235, 235, 235), 2)
        self.assertEqual(il.detect_labels(img, il.PICK_RECT), [])


if __name__ == "__main__":
    unittest.main()
