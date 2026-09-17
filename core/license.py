"""GameBot 라이선스 관리 — 사용자가 프리티켓(무료 체험) 발급.

월정액 11만원. 사용자가 직접 티켓을 생성/발급한다.
"""
import json
import hashlib
import time
from pathlib import Path

LICENSE_FILE = Path.home() / ".gamebot" / "license.json"
PRICE_MONTHLY = 110000  # 월 11만원
TRIAL_DAYS = 0           # 프리티켓 없음 — 유료만

# 사용자(관리자)가 발급하는 티켓 — 실제 운영에서는 중앙 서버 검증으로 확장
ISSUER_SECRET = "gamebot-2024-olmoon"


def issue_ticket(days: int = 30, plan: str = "monthly") -> dict:
    """프리티켓 발급 (사용자 전용 — 봇이 호출하지 않음)."""
    expires = time.time() + days * 86400
    payload = f"{plan}:{expires}:{ISSUER_SECRET}"
    key = hashlib.sha256(payload.encode()).hexdigest()[:32]
    return {
        "plan": plan,          # trial / monthly
        "days": days,
        "price": PRICE_MONTHLY if plan == "monthly" else 0,
        "expires": expires,
        "key": key,
        "issued": time.time(),
    }


def save_ticket(ticket: dict):
    LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LICENSE_FILE.write_text(json.dumps(ticket, ensure_ascii=False, indent=2))


def load_ticket() -> dict | None:
    try:
        return json.loads(LICENSE_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return None


def is_valid() -> bool:
    """라이선스 유효 여부 — 만료/없으면 False."""
    t = load_ticket()
    if not t:
        return False
    # 키 검증
    payload = f'{t.get("plan")}:{t.get("expires")}:{ISSUER_SECRET}'
    expected = hashlib.sha256(payload.encode()).hexdigest()[:32]
    if t.get("key") != expected:
        return False
    return time.time() < t.get("expires", 0)


def status() -> dict:
    t = load_ticket() or {}
    remaining = max(0, t.get("expires", 0) - time.time())
    return {
        "valid": is_valid(),
        "plan": t.get("plan", "없음"),
        "remaining_days": round(remaining / 86400, 1),
        "price": PRICE_MONTHLY,
    }


def activate(key: str) -> bool:
    """사용자가 받은 키로 활성화."""
    t = load_ticket()
    if t and t.get("key") == key:
        return is_valid()
    return False


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="GameBot 라이선스")
    ap.add_argument("cmd", choices=["issue", "status", "activate"])
    ap.add_argument("--days", type=int, default=TRIAL_DAYS)
    ap.add_argument("--plan", default="trial", choices=["trial", "monthly"])
    ap.add_argument("--key")
    args = ap.parse_args()

    if args.cmd == "issue":
        t = issue_ticket(args.days, args.plan)
        save_ticket(t)
        print(f"✅ {args.plan} 티켓 발급 ({args.days}일, ₩{t['price']:,})")
        print(f"   키: {t['key']}")
        print(f"   파일: {LICENSE_FILE}")
    elif args.cmd == "status":
        s = status()
        print(f"라이선스: {'✅ 유효' if s['valid'] else '❌ 만료/없음'}")
        print(f"플랜: {s['plan']} · 잔여 {s['remaining_days']}일 · ₩{s['price']:,}/월")
    elif args.cmd == "activate" and args.key:
        print("✅ 활성화됨" if activate(args.key) else "❌ 키 불일치")
