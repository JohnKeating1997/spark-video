from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.gate import gate_render


class GateReviewPolicyTests(unittest.TestCase):
    def _episode(self, *, blocking_issues: list[dict]) -> Path:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        (root / "clips").mkdir()
        (root / "clips" / "S01-001.mp4").write_bytes(b"placeholder")
        (root / "storyboard.json").write_text(json.dumps({
            "shots": [{"id": "S01-001", "prompt": "test"}],
        }))
        review = {
            "score": 6.5,
            "verdict": "REJECT",
            "blocking_issues": blocking_issues,
        }
        (root / "shots_state.json").write_text(json.dumps({
            "S01-001": {
                "winner_version": 1,
                "manual_acceptance": True,
                "attempts": [{"version": 1, "review": review}],
            },
        }))
        return root

    def test_manual_best_of_n_without_blocker_can_pass(self) -> None:
        result = gate_render(self._episode(blocking_issues=[]))
        self.assertTrue(result.passed)

    def test_manual_best_of_n_cannot_override_blocker(self) -> None:
        result = gate_render(self._episode(blocking_issues=[{
            "type": "wrong_speaker",
            "detail": "The wrong person speaks.",
        }]))
        self.assertFalse(result.passed)


if __name__ == "__main__":
    unittest.main()
