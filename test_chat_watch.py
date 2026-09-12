"""채팅 OCR 기반 줍기 판정을 검증한다 (SPEC-1032722)."""
import unittest
from unittest.mock import patch

import numpy as np

import chat_watch


class ChatWatchTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((1332, 1933, 3), dtype=np.uint8)

    def test_crop_stays_in_frame(self):
        """채팅 rect 가 캡처 해상도를 벗어나지 않아야 한다."""
        x0, y0, x1, y1 = chat_watch.CHAT_RECT
        h, w = self.frame.shape[:2]
        self.assertLess(x0, x1)
        self.assertLess(y0, y1)
        self.assertLessEqual(x1, w)
        self.assertLessEqual(y1, h)
        self.assertGreater(chat_watch._preprocess(self.frame).size, 0)

    def test_counts_only_pickup_lines(self):
        chat = (
            "회복의 기운이 느껴집니다.\n"
            "아데나 (68) 을(를) 획득하였습니다.\n"
            "몸 속 깊은 곳에서 피가 끓어오르는 것을 느낍니다.\n"
            "아데나 (14) 을(를) 획득하였습니다.\n"
        )
        with patch.object(chat_watch, "read_chat", return_value=chat):
            self.assertEqual(chat_watch.pickup_count(self.frame), 2)

    def test_no_pickup_message_counts_zero(self):
        """회복 메시지만 흐르는 평상시에는 0이어야 한다(거짓 성공 방지)."""
        chat = "회복의 기운이 느껴집니다.\n회복의 기운이 느껴집니다.\n"
        with patch.object(chat_watch, "read_chat", return_value=chat):
            self.assertEqual(chat_watch.pickup_count(self.frame), 0)

    def test_ocr_failure_is_not_a_pickup(self):
        """OCR 이 실패해도 예외 없이 0 — 실패를 성공으로 오판하지 않는다."""
        with patch.object(chat_watch.subprocess, "run",
                          side_effect=FileNotFoundError):
            self.assertEqual(chat_watch.pickup_count(self.frame), 0)


if __name__ == "__main__":
    unittest.main()
