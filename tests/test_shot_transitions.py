from __future__ import annotations

import unittest

from lib.storyboard import Shot, ShotTransition


def _shot(**overrides) -> Shot:
    data = {
        "id": "S01-002",
        "scene": "S01",
        "duration": 5,
        "prompt": "The subject turns toward the door.",
        "narrative_purpose": "Continue the visible action.",
        "speech_source": "none",
        "use_prev_last_frame_as_first": False,
    }
    data.update(overrides)
    return Shot.model_validate(data)


class ShotTransitionTests(unittest.TestCase):
    def test_continuous_action_enables_exact_frame_bridge(self) -> None:
        shot = _shot(transition_from_previous={"type": "continuous_action"})
        self.assertTrue(shot.use_prev_last_frame_as_first)

    def test_other_transition_disables_exact_frame_bridge(self) -> None:
        shot = _shot(
            use_prev_last_frame_as_first=True,
            transition_from_previous={
                "type": "shot_reverse_shot",
                "preserve": ["eyeline", "lighting"],
                "allow_change": ["camera_angle"],
            },
        )
        self.assertFalse(shot.use_prev_last_frame_as_first)

    def test_legacy_flag_remains_compatible_without_transition(self) -> None:
        self.assertTrue(_shot(use_prev_last_frame_as_first=True).use_prev_last_frame_as_first)

    def test_transition_rejects_conflicting_attributes(self) -> None:
        with self.assertRaisesRegex(ValueError, "both preserved and allowed"):
            ShotTransition.model_validate({
                "type": "same_scene_cut",
                "preserve": ["lighting"],
                "allow_change": ["lighting"],
            })


if __name__ == "__main__":
    unittest.main()
