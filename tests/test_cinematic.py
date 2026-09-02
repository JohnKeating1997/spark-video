from __future__ import annotations

import unittest

from lib.cinematic import cinematic_budget


class CinematicBudgetTests(unittest.TestCase):
    def test_five_second_shot_is_single_action(self) -> None:
        budget = cinematic_budget(5)
        self.assertEqual(budget["tier"], "micro")
        self.assertEqual(budget["label"], "micro shot · 2-5s")
        self.assertIn("causally linked micro-phases", budget["prompt_guidance"])
        self.assertIn("微阶段", budget["prompt_guidance_zh"])

    def test_eight_second_shot_is_the_core_prior(self) -> None:
        budget = cinematic_budget(8)
        self.assertEqual(budget["tier"], "core")
        self.assertEqual(budget["label"], "core shot · 6-10s")

    def test_fifteen_second_shot_is_extended(self) -> None:
        budget = cinematic_budget(15)
        self.assertEqual(budget["tier"], "extended")
        self.assertEqual(budget["label"], "extended shot · 11-15s")

    def test_thirty_second_shot_is_exceptional_without_a_beat_quota(self) -> None:
        budget = cinematic_budget(30)
        self.assertEqual(budget["tier"], "exceptional")
        self.assertEqual(budget["label"], "exceptional long take · 16-30s")
        self.assertNotIn("min_beats", budget)
        self.assertNotIn("max_beats", budget)


if __name__ == "__main__":
    unittest.main()
