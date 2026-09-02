from __future__ import annotations

import unittest

from scripts.storyboard import _targeted_animatic_panels


class AnimaticTargetingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.panels = [
            {"id": "S01-001", "shots": ["S01-001"], "candidates": ["keep-a"]},
            {"id": "S02-003", "shots": ["S02-003"], "candidates": ["replace"]},
            {"id": "S03-002", "shots": ["S03-002"], "candidates": ["keep-b"]},
        ]

    def test_no_target_keeps_full_episode_behavior(self) -> None:
        self.assertIs(_targeted_animatic_panels(self.panels, []), self.panels)

    def test_one_target_returns_only_that_shot_panel(self) -> None:
        selected = _targeted_animatic_panels(self.panels, ["S02-003"])
        self.assertEqual([panel["id"] for panel in selected], ["S02-003"])

        selected[0]["candidates"] = []
        self.assertEqual(self.panels[0]["candidates"], ["keep-a"])
        self.assertEqual(self.panels[2]["candidates"], ["keep-b"])

    def test_repeated_targets_preserve_storyboard_order(self) -> None:
        selected = _targeted_animatic_panels(
            self.panels, ["S03-002", "S01-001"],
        )
        self.assertEqual(
            [panel["id"] for panel in selected],
            ["S01-001", "S03-002"],
        )


if __name__ == "__main__":
    unittest.main()
