"""GameBot 실행 게이트 — 라이선스 검증 후 봇 실행."""
from core import license


def check_and_run(run_func, *args, **kwargs):
    s = license.status()
    if not s["valid"]:
        print(f"❌ 라이선스 만료 — 월 ₩{s['price']:,}")
        print(f"   잔여: {s['remaining_days']}일")
        print("   관리자에게 티켓 키를 받아주세요:")
        print("   python3 core/license.py activate --key <키>")
        return None
    print(f"✅ 라이선스 유효 ({s['plan']}, 잔여 {s['remaining_days']}일)")
    return run_func(*args, **kwargs)
