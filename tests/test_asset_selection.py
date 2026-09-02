from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_viewer import _collect_entities
from scripts.scaffold import (
    _read_selected_image,
    _scan_tier_folders,
    _write_recommended_image,
    _write_selected_image,
)


class AssetSelectionTests(unittest.TestCase):
    def test_selection_sidecar_chooses_one_existing_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            asset_dir = Path(tmp)
            old = asset_dir / "Wan_old.png"
            chosen = asset_dir / "new-reference.png"
            old.write_bytes(b"old")
            chosen.write_bytes(b"new")
            _write_selected_image(asset_dir, chosen)
            self.assertEqual(
                _read_selected_image(asset_dir, [str(old), str(chosen)]),
                str(chosen),
            )

    def test_viewer_places_manifest_selection_before_folder_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            parent = root / "cast"
            asset_dir = parent / "Elio"
            asset_dir.mkdir(parents=True)
            (asset_dir / "cast.md").write_text("# Elio", encoding="utf-8")
            old = asset_dir / "Wan_old.png"
            chosen = asset_dir / "portrait1.png"
            old.write_bytes(b"old")
            chosen.write_bytes(b"new")
            entries = {"Elio": {"images": [str(chosen)]}}

            entities = _collect_entities(parent, root, "cast.md", entries)

            self.assertEqual(
                entities[0]["selected_image"], "cast/Elio/portrait1.png"
            )
            self.assertEqual(
                entities[0]["images"][0], "cast/Elio/portrait1.png"
            )
            self.assertIn("cast/Elio/Wan_old.png", entities[0]["images"])

    def test_invalid_sidecar_does_not_escape_asset_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            asset_dir = Path(tmp)
            outside = asset_dir.parent / "outside.png"
            outside.write_bytes(b"outside")
            (asset_dir / ".asset-selection.json").write_text(
                json.dumps({"selected_image": "../outside.png"}),
                encoding="utf-8",
            )
            self.assertIsNone(_read_selected_image(asset_dir, [str(outside)]))

    def test_agent_recommendation_is_active_manifest_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            parent = root / "props"
            asset_dir = parent / "yellow-pencil"
            asset_dir.mkdir(parents=True)
            (asset_dir / "prop.md").write_text("# Pencil", encoding="utf-8")
            first = asset_dir / "candidate-01.png"
            recommended = asset_dir / "candidate-02.png"
            first.write_bytes(b"first")
            recommended.write_bytes(b"recommended")
            _write_recommended_image(asset_dir, recommended)

            manifest = _scan_tier_folders(parent, ["prop.md"])
            entities = _collect_entities(parent, root, "prop.md", manifest)

            self.assertEqual(
                entities[0]["selected_image"],
                "props/yellow-pencil/candidate-02.png",
            )
            self.assertEqual(
                entities[0]["recommended_image"],
                "props/yellow-pencil/candidate-02.png",
            )
            self.assertEqual(len(entities[0]["images"]), 2)

            self.assertEqual(
                manifest["yellow-pencil"]["images"], [str(recommended)]
            )
            self.assertEqual(
                manifest["yellow-pencil"]["selected_image"], str(recommended)
            )
            self.assertEqual(
                manifest["yellow-pencil"]["recommended_image"], str(recommended)
            )
            self.assertNotIn("selection_required", manifest["yellow-pencil"])


if __name__ == "__main__":
    unittest.main()
