#!/usr/bin/env python3
"""GameBot 실행기 — 게임 프로필 선택 후 봇/줍기 기동.

사용법:
    python3 run.py hunt          # 사냥 봇 (물약)
    python3 run.py pick          # 줍기 봇
    python3 run.py all           # 둘 다
    python3 run.py --game lineage_classic hunt   # 게임 지정
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent

GAMES = {
    "lineage_classic": {
        "hunt": "games/lineage_classic/hunt_bot.py",
        "pick": "games/lineage_classic/picker.py",
    },
}


def main():
    ap = argparse.ArgumentParser(description="GameBot 실행기")
    ap.add_argument("mode", choices=["hunt", "pick", "all"], help="hunt=사냥 pick=줍기 all=둘다")
    ap.add_argument("--game", default="lineage_classic", help="게임 프로필")
    args = ap.parse_args()

    game = GAMES.get(args.game)
    if not game:
        print(f"게임 '{args.game}' 없음. 가능: {list(GAMES)}")
        sys.exit(1)

    scripts = []
    if args.mode in ("hunt", "all"):
        scripts.append(("linc-hunt", game["hunt"]))
    if args.mode in ("pick", "all"):
        scripts.append(("linc-aden", game["pick"]))

    # 라이선스 체크
    sys.path.insert(0, str(ROOT))
    from core import license
    s = license.status()
    if not s["valid"]:
        print(f"❌ 라이선스 만료 — 월 ₩{s['price']:,}")
        print(f"   관리자에게 티켓을 받으세요. 잔여: {s['remaining_days']}일")
        sys.exit(1)
    print(f"✅ 라이선스 유효 ({s['plan']}, {s['remaining_days']}일)")

    for name, script in scripts:
        cmd = f'tmux new-session -d -s {name} "cd {ROOT} && python3 {script} >> /tmp/{name}.log 2>&1"'
        subprocess.run(cmd, shell=True)
        print(f"✓ {name} 기동 → {script} (로그: /tmp/{name}.log)")


if __name__ == "__main__":
    main()
