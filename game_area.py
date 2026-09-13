"""게임 화면 영역 확정 (BTS: 줍기 획득 0 원인)

런처 패널이 열리거나 창 크기가 바뀌면 하드코딩 좌표(PICK_RECT/CHAT_RECT)가
통째로 빗나간다. 퍼플온은 게임을 <video> 엘리먼트로 스트리밍하므로,
CDP DOM에서 얻은 video rect를 판독 좌표계로 환산해 기준으로 삼는다.

픽셀 휴리스틱(가장 큰 컬러 연결성분)은 런처의 스트리밍 썸네일을 게임 화면으로
오인해 폐기했다. DOM rect는 레이아웃 변화에 항상 정확하다.
"""

# 게임(video) 영역 기준 상대 비율 (0~1). 실측 대조 완료.
CHAT_REL = (0.18, 0.82, 0.76, 1.00)   # 채팅 로그
PICK_REL = (0.02, 0.02, 0.99, 0.76)   # 바닥 드랍 탐색 (하단 UI 바 제외)

# DOM 조회 실패 시 폴백 (2026-09-27 실측: 창 800x600, 런처 패널 열림)
FALLBACK_RECT = (968, 356, 1930, 1019)


def game_rect(win=None):
    """게임 영역 (x0, y0, x1, y1) — 판독 좌표계(WINDOW_SIZE) 기준."""
    if win is not None:
        try:
            r = win.video_read_rect()
            if r and r[2] - r[0] > 50 and r[3] - r[1] > 50:
                return r
        except Exception:
            pass
    return FALLBACK_RECT


def rel_to_abs(rel, rect):
    """상대비율 → 절대좌표."""
    x0, y0, x1, y1 = rect
    gw, gh = x1 - x0, y1 - y0
    return (int(x0 + rel[0] * gw), int(y0 + rel[1] * gh),
            int(x0 + rel[2] * gw), int(y0 + rel[3] * gh))


def rel_to_img(rel, img):
    """상대비율 → capture_game() 이미지 내 좌표.

    capture_game()이 돌려주는 프레임은 게임 화면 그 자체(0,0~vw,vh)라
    이미지 전체가 곧 게임 영역이다. 화면 절대좌표로 환산하는
    rel_to_abs와 달리 video rect 조회가 필요 없고, 스트림 해상도가
    도중에 바뀌어도 비율이 유지되므로 어긋나지 않는다.
    """
    h, w = img.shape[:2]
    return (int(rel[0] * w), int(rel[1] * h),
            int(rel[2] * w), int(rel[3] * h))


def crop_rel(img, rel):
    """capture_game() 프레임에서 해당 영역만 잘라낸다."""
    x0, y0, x1, y1 = rel_to_img(rel, img)
    return img[y0:y1, x0:x1]


def pick_rect(win=None):
    """바닥 드랍 탐색 영역."""
    return rel_to_abs(PICK_REL, game_rect(win))


def chat_rect(win=None):
    """채팅 로그 영역."""
    return rel_to_abs(CHAT_REL, game_rect(win))


def regions(win=None):
    """(game_rect, pick_rect, chat_rect)."""
    g = game_rect(win)
    return g, rel_to_abs(PICK_REL, g), rel_to_abs(CHAT_REL, g)


if __name__ == "__main__":
    import cv2
    from cdp_window import CdpWindow
    w = CdpWindow()
    im = w.capture()
    g, p, c = regions(w)
    print("game:", g, " pick:", p, " chat:", c)
    vis = im.copy()
    for r, col, name in ((g, (0, 255, 0), "game"), (p, (0, 255, 255), "pick"),
                         (c, (255, 0, 255), "chat")):
        cv2.rectangle(vis, r[:2], r[2:], col, 3)
        cv2.putText(vis, name, (r[0] + 6, r[1] + 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, col, 2)
    cv2.imwrite("/tmp/diag_regions.png", vis)
    print("→ /tmp/diag_regions.png")
