"""클릭 양보가 120초 동안 물약을 막으면 안 된다."""
import time

import onestep_hunt as oh


class Dummy:
    def click(self, *a, **k):
        raise AssertionError("조작 중이면 클릭하지 않는다")

    def geometry(self):
        return (0, 0, 1, 1)


def test_사용자_조작중이면_즉시_생략():
    oh.user_active = lambda observe=0.12, poll=0.04: True
    t0 = time.monotonic()
    try:
        oh.yield_click(Dummy(), 10, 10)
        assert False, "UserBusy 여야 한다"
    except oh.UserBusy:
        pass
    assert time.monotonic() - t0 < 0.5
