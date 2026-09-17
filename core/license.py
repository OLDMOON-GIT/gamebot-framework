"""GameBot 라이선스 — 유료(월 11만원) + 관리자 프리 키 (1PC/1계정 고정).

프리 키는 사용자가 별도 발급. 해당 PC에서만 유효하고 1계정만 사용 가능.
"""
import json
import hashlib
import subprocess
import time
from pathlib import Path

LICENSE_FILE = Path.home() / ".gamebot" / "license.json"
PRICE_MONTHLY = 110000
ISSUER_SECRET = "gamebot-2024-olmoon"


def _machine_id() -> str:
    """이 PC를 식별하는 고유 ID (MAC + CPU)."""
    try:
        mac = subprocess.check_output(
            ["cat", "/sys/class/net/eno1/address"],
            timeout=3, text=True).strip()
    except Exception:
        mac = "unknown"
    try:
        cpu = subprocess.check_output(
            ["grep", "-m1", "model name", "/proc/cpuinfo"],
            timeout=3, text=True).split(":")[1].strip()
    except Exception:
        cpu = "unknown"
    return hashlib.sha256(f"{mac}:{cpu}".encode()).hexdigest()[:16]


def issue_monthly(days: int = 30) -> dict:
    """월정액 티켓 (유료 ₩110,000)."""
    expires = time.time() + days * 86400
    return _sign({"plan": "monthly", "days": days, "price": PRICE_MONTHLY, "expires": expires})


def issue_free(days: int = 30, account: str = "", machine: str = "") -> dict:
    """프리 키 (관리자 발급 — 1PC/1계정 고정).

    Args:
        days: 유효 기간
        account: 이 키를 쓸 계정명 (지정 안 하면 발급 시점 계정)
        machine: 이 키를 쓸 PC의 machine_id (지정 안 하면 발급 시점 PC)
    """
    if not account:
        account = _get_account()
    if not machine:
        machine = _machine_id()
    expires = time.time() + days * 86400
    return _sign({
        "plan": "free",
        "days": days,
        "price": 0,
        "account": account,
        "machine": machine,
        "expires": expires,
    })


def _sign(data: dict) -> dict:
    payload = json.dumps(data, sort_keys=True) + ISSUER_SECRET
    data["key"] = hashlib.sha256(payload.encode()).hexdigest()[:40]
    data["issued"] = time.time()
    return data


def _get_account() -> str:
    """현재 사용자 계정."""
    import os
    return os.environ.get("USER", os.environ.get("USERNAME", "unknown"))


def save(ticket: dict):
    LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LICENSE_FILE.write_text(json.dumps(ticket, ensure_ascii=False, indent=2))


def load() -> dict | None:
    try:
        return json.loads(LICENSE_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return None


def is_valid() -> bool:
    t = load()
    if not t:
        return False
    # 서명 검증
    data = {k: v for k, v in t.items() if k not in ("key", "issued")}
    payload = json.dumps(data, sort_keys=True) + ISSUER_SECRET
    expected = hashlib.sha256(payload.encode()).hexdigest()[:40]
    if t.get("key") != expected:
        return False
    # 만료
    if time.time() > t.get("expires", 0):
        return False
    # 프리 키: PC 고정 + 계정 고정
    if t.get("plan") == "free":
        if t.get("machine") != _machine_id():
            return False  # 다른 PC에서는 사용 불가
        if t.get("account") != _get_account():
            return False  # 다른 계정에서는 사용 불가
    return True


def status() -> dict:
    t = load() or {}
    remaining = max(0, t.get("expires", 0) - time.time())
    return {
        "valid": is_valid(),
        "plan": t.get("plan", "없음"),
        "remaining_days": round(remaining / 86400, 1),
        "price": t.get("price", PRICE_MONTHLY),
        "machine": _machine_id(),
        "account": t.get("account", _get_account()),
        "locked_pc": t.get("plan") == "free",
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="GameBot 라이선스")
    ap.add_argument("cmd", choices=["issue-monthly", "issue-free", "status"])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--account")
    args = ap.parse_args()

    if args.cmd == "issue-monthly":
        t = issue_monthly(args.days)
        save(t)
        print(f"✅ 월정액 티켓 ({args.days}일, ₩{PRICE_MONTHLY:,})")
        print(f"   키: {t['key']}")
    elif args.cmd == "issue-free":
        t = issue_free(args.days, args.account or "")
        save(t)
        print(f"✅ 프리 키 ({args.days}일, PC: {t['machine'][:8]}..., 계정: {t['account']})")
        print(f"   ⚠️ 이 키는 발급한 PC({t['machine'][:8]}...)에서만 사용 가능")
        print(f"   키: {t['key']}")
    elif args.cmd == "status":
        s = status()
        print(f"라이선스: {'✅' if s['valid'] else '❌'}")
        print(f"플랜: {s['plan']} · 잔여 {s['remaining_days']}일")
        print(f"PC ID: {s['machine']}")
        print(f"계정: {s['account']}")
        if s['locked_pc']:
            print(f"🔒 PC 고정 (다른 PC 사용 불가)")
