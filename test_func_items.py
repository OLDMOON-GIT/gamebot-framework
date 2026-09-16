from func_items import next_item, ready

GREEN = {"itemId": "green", "name": "초록 물약", "hotkey": "F7",
         "enabled": True, "triggerType": "TIMER", "duration": 300, "refreshBefore": 10}
ANTI = {"itemId": "antidote", "name": "해독제", "hotkey": "F2",
        "enabled": True, "triggerType": "STATUS", "status": "poisoned"}


def test_타이머_첫사용():
    assert next_item([GREEN], 0, {}, {}).get("itemId") == "green"


def test_지속중이면_안씀():
    assert next_item([GREEN], 50, {"green": 0}, {}) is None


def test_만료전_refreshBefore에_재사용():
    assert ready(GREEN, 295, 0, {}) is True  # remain 5 <= 10


def test_해독은_독일때만():
    assert next_item([ANTI], 1, {}, {}) is None
    assert next_item([ANTI], 1, {}, {"poisoned": True}).get("hotkey") == "F2"


def test_핫키없으면_스킵():
    it = {**GREEN, "hotkey": ""}
    assert next_item([it], 0, {}, {}) is None
