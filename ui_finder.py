"""화면에서 UI 버튼을 템플릿 매칭으로 찾는다 — 고정 좌표 폐기(협의안).

템플릿은 사람이 한 번 crop한 assets/ui/*.png. TM_CCOEFF_NORMED만 쓴다
(TM_SQDIFF는 최소값이 최적이라 혼용 시 조용히 망가진다 — 협의 지적).
"""

from pathlib import Path

import cv2

ASSET_DIR = Path(__file__).parent / "assets" / "ui"
MATCH_THRESHOLD = 0.80


def find_button(frame, template_name, threshold=MATCH_THRESHOLD):
    """프레임에서 버튼을 찾아 (x, y, 점수)를 반환. 없으면 None."""
    path = ASSET_DIR / f"{template_name}.png"
    if not path.exists():
        return None
    template = cv2.imread(str(path))
    if template is None or frame is None or \
            template.shape[0] >= frame.shape[0] or template.shape[1] >= frame.shape[1]:
        return None
    result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(result)
    if score < threshold:
        return None
    h, w = template.shape[:2]
    return loc[0] + w // 2, loc[1] + h // 2, float(score)


def save_template(frame, x0, y0, x1, y1, template_name):
    """사람이 지정한 영역을 템플릿으로 적립한다(실측 1회)."""
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    patch = frame[y0:y1, x0:x1]
    if patch.size == 0:
        raise ValueError("템플릿 영역이 비었습니다")
    cv2.imwrite(str(ASSET_DIR / f"{template_name}.png"), patch)
    return template_name
