"""사냥 기록(hunt_log.jsonl)으로 사냥터 우선순위를 자동 조정한다.

사용자 설계 13번: 경험치 + 생존 + 물약 소비량 기준. 경험치 판독은
화면 좌표 실측 후 연결되고, 우선 기록 가능한 지표(사망/분당 물약/
지속 성공)로 점수를 매긴다. 점수가 낮을수록 우선.
"""

import json
import time
from collections import defaultdict
from pathlib import Path

LOG_PATH = Path(__file__).parent / "hunt_log.jsonl"


def rank_grounds(records, *, recent_days=3):
    """기록 목록에서 사냥터별 점수를 계산한다(낮을수록 우선).

    death 1회 +5점, 분당 물약 소비 +2점, 정상 귀환(5분 이상 지속) -1점.
    기록이 없는 사냥터는 중간값 0점으로 두어 새 사냥터를 폐쇄하지 않는다.
    """
    cutoff = time.time() - recent_days * 86400
    scores = defaultdict(list)
    for record in records:
        if record.get("t", 0) < cutoff:
            continue
        name = record.get("ground")
        if not name:
            continue
        # v2 로그 스키마: death 대신 reason(hp_danger) + emergency 횟수.
        danger = bool(record.get("death")) or record.get("reason") == "hp_danger"
        score = 0.0
        if danger:
            score += 5
        score += 2 * record.get("emergency", 0)
        minutes = max(0.1, record.get("minutes", 0))
        score += 2 * record.get("potions", 0) / minutes
        if not danger and minutes >= 5:
            score -= 1
        scores[name].append(score)
    return {name: round(sum(vals) / len(vals), 2) for name, vals in scores.items()}


def order_config_grounds(config, records):
    """config의 hunting_grounds를 점수 오름차순(우선)으로 재배열해 반환."""
    scores = rank_grounds(records)
    grounds = list(config.get("hunting_grounds", []))
    grounds.sort(key=lambda g: scores.get(g.get("name"), 0.0))
    return grounds


def load_records(path=LOG_PATH):
    if not Path(path).exists():
        return []
    records = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records
