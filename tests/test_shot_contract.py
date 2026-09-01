from __future__ import annotations

import unittest

from lib.shot_contract import (
    approval_contract,
    contract_fingerprint,
    contract_mismatches,
    storyboard_contract_fingerprint,
)


class ShotContractTests(unittest.TestCase):
    def _shot(self) -> dict:
        return {
            "id": "S01-001",
            "scene": "S01",
            "duration": 5,
            "kind": "r2v",
            "role": "narration",
            "prompt": "latest render wording",
            "animatic_prompt": "teacher beside a green leaf",
            "narrative_purpose": "introduce the process",
            "narration_text": "This is the process.",
            "characters": ["teacher"],
            "props": ["leaf"],
            "set_id": "classroom",
        }

    def test_literal_rewrite_keeps_approved_animatic_contract(self) -> None:
        shot = self._shot()
        before = contract_fingerprint(shot)
        shot["prompt"] = "rewritten model-facing wording"
        self.assertEqual(contract_fingerprint(shot), before)

    def test_visual_or_narrative_change_invalidates_contract(self) -> None:
        shot = self._shot()
        before = contract_fingerprint(shot)
        shot["animatic_prompt"] = "teacher alone, no leaf"
        self.assertNotEqual(contract_fingerprint(shot), before)

    def test_transition_change_invalidates_contract(self) -> None:
        shot = self._shot()
        before = contract_fingerprint(shot)
        shot["transition_from_previous"] = {
            "type": "same_scene_cut",
            "preserve": ["lighting"],
            "allow_change": ["camera_angle"],
        }
        self.assertNotEqual(contract_fingerprint(shot), before)

    def test_prompt_is_contract_when_animatic_prompt_is_absent(self) -> None:
        shot = self._shot()
        shot["animatic_prompt"] = None
        before = contract_fingerprint(shot)
        shot["prompt"] = "different composition"
        self.assertNotEqual(contract_fingerprint(shot), before)

    def test_manifest_mismatch_is_reported(self) -> None:
        shot = self._shot()
        storyboard = {"shots": [shot], "target_duration_s": 30, "ratio": "16:9"}
        manifest = {
            "storyboard_contract_fingerprint": storyboard_contract_fingerprint(
                storyboard
            ),
            "panels": [{
                "shots": [shot["id"]],
                "contract_fingerprints": {
                    shot["id"]: contract_fingerprint(shot),
                },
                "contract_snapshots": {
                    shot["id"]: approval_contract(shot),
                },
            }]
        }
        self.assertEqual(contract_mismatches(storyboard, manifest), [])
        storyboard["shots"][0]["narration_text"] = "Changed narration"
        self.assertEqual(contract_mismatches(storyboard, manifest), ["S01-001"])

    def test_episode_level_change_invalidates_approval(self) -> None:
        shot = self._shot()
        storyboard = {"shots": [shot], "target_duration_s": 30, "ratio": "16:9"}
        manifest = {
            "storyboard_contract_fingerprint": storyboard_contract_fingerprint(
                storyboard
            ),
            "panels": [{
                "shots": [shot["id"]],
                "contract_fingerprints": {
                    shot["id"]: contract_fingerprint(shot),
                },
            }],
        }
        storyboard["ratio"] = "9:16"
        self.assertEqual(contract_mismatches(storyboard, manifest), ["<storyboard>"])


if __name__ == "__main__":
    unittest.main()
