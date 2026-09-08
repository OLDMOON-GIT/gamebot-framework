"""사냥터 우선순위 자동 조정 검증."""
import time
import unittest

from ground_ranker import order_config_grounds, rank_grounds

NOW = time.time()


def rec(ground, minutes, potions, death=False, t=NOW):
    return {"ground": ground, "minutes": minutes, "potions": potions,
            "death": death, "t": t}


class RankerTests(unittest.TestCase):
    def test_death_and_potion_burn_raise_score(self):
        """사망 잦고 물약 태우는 사냥터는 점수가 높다(=우선순위 하락)."""
        scores = rank_grounds([
            rec("A", 60, 600), rec("A", 60, 600, death=True),
            rec("B", 60, 100), rec("B", 60, 100),
        ])
        self.assertGreater(scores["A"], scores["B"])

    def test_b_vs_a_efficiency_choice(self):
        """설계 예시: 경험치 10% 낮아도 물약 600→100이면 B가 우선."""
        scores = rank_grounds([rec("A", 60, 600), rec("B", 60, 100)])
        self.assertLess(scores["B"], scores["A"])

    def test_stale_records_ignored(self):
        old = rec("A", 60, 600, t=NOW - 5 * 86400)
        self.assertEqual(rank_grounds([old]), {})

    def test_unrecorded_ground_keeps_neutral(self):
        config = {"hunting_grounds": [{"name": "신터"}, {"name": "A"}]}
        ordered = order_config_grounds(config, [rec("A", 60, 600, death=True)])
        self.assertEqual([g["name"] for g in ordered], ["신터", "A"])


if __name__ == "__main__":
    unittest.main()
