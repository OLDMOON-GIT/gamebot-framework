"""캘리브레이션이 OCR 정수 없이 게이지 ratio로도 통과해야 한다."""
import onestep_hunt as oh

oh.time.sleep = lambda s: None


class RatioOnly:
    def read(self):
        return 0.42

    def probe(self):
        return None


def test_ratio만_있어도_캘리브레이션_통과():
    got = oh.calibrate_hud(RatioOnly(), need=3, tries=5, delay=0)
    assert got == (420, 1000)
