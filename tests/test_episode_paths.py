from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lib import model_log
from lib.state import normalize_episode_id


class EpisodePathTests(unittest.TestCase):
    def test_normalize_prefixes_plain_id(self) -> None:
        self.assertEqual(normalize_episode_id("001"), "episode-001")

    def test_normalize_prefixes_punctuated_id(self) -> None:
        self.assertEqual(
            normalize_episode_id("anime-wan3.0"),
            "episode-anime-wan3.0",
        )

    def test_normalize_preserves_canonical_id(self) -> None:
        self.assertEqual(
            normalize_episode_id("episode-anime-wan3.0"),
            "episode-anime-wan3.0",
        )

    def test_model_log_uses_same_punctuated_id_rule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            projects_dir = Path(tmp)
            settings = SimpleNamespace(projects_dir=projects_dir)
            with patch.object(model_log, "SETTINGS", settings):
                path = model_log._log_path_for("demo", "anime-wan3.0")
        self.assertEqual(
            path,
            projects_dir
            / "demo"
            / "episode-anime-wan3.0"
            / "logs"
            / "model_calls.jsonl",
        )


if __name__ == "__main__":
    unittest.main()
