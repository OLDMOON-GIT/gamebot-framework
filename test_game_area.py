"""game_area 상대비율 환산 테스트.

캡처 경로가 두 갈래(CSS 뷰포트 capture / 원본 해상도 capture_game)로
나뉘면서, 판독 영역을 절대 rect 상수로 들고 있으면 한쪽에서 반드시
어긋난다. 비율 기반 환산이 양쪽 해상도에서 같은 영역을 가리키는지
고정한다.
"""
import numpy as np

from game_area import CHAT_REL, PICK_REL, crop_rel, rel_to_abs, rel_to_img


def _img(w, h):
    return np.zeros((h, w, 3), np.uint8)


def test_rel_to_img_maps_full_frame_as_game_area():
    # capture_game 프레임은 게임 화면 그 자체 → 비율 * 이미지크기
    x0, y0, x1, y1 = rel_to_img(CHAT_REL, _img(1280, 960))
    assert (x0, y0, x1, y1) == (int(0.18 * 1280), int(0.82 * 960),
                                int(0.76 * 1280), int(1.00 * 960))


def test_crop_rel_returns_expected_size():
    crop = crop_rel(_img(1280, 960), PICK_REL)
    h, w = crop.shape[:2]
    assert w == int(0.99 * 1280) - int(0.02 * 1280)
    assert h == int(0.76 * 960) - int(0.02 * 960)


def test_same_region_across_resolutions():
    """스트림 해상도가 바뀌어도 같은 비율 영역을 가리켜야 한다."""
    small = crop_rel(_img(640, 480), CHAT_REL)
    big = crop_rel(_img(1280, 960), CHAT_REL)
    sh, sw = small.shape[:2]
    bh, bw = big.shape[:2]
    assert abs(bw - sw * 2) <= 2
    assert abs(bh - sh * 2) <= 2


def test_crop_is_non_empty():
    """비율이 뒤집히거나 0폭이 되면 판독이 조용히 실패한다."""
    for rel in (CHAT_REL, PICK_REL):
        for size in ((398, 299), (1280, 960), (1920, 1080)):
            crop = crop_rel(_img(*size), rel)
            assert crop.size > 0, (rel, size)


def test_rel_to_abs_still_offsets_by_rect():
    """기존 절대좌표 경로(로비/웹 UI)는 그대로 동작해야 한다."""
    assert rel_to_abs((0.0, 0.0, 1.0, 1.0), (100, 200, 300, 500)) == (
        100, 200, 300, 500)
    assert rel_to_abs((0.5, 0.5, 1.0, 1.0), (0, 0, 200, 400)) == (
        100, 200, 200, 400)
