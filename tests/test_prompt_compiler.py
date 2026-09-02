from __future__ import annotations

import unittest

from lib.prompt_compiler import (
    art_direction_conflicts,
    compatible_art_direction,
    infer_visual_medium,
    normalize_visual_medium,
    reference_treatment_instruction,
    rendering_instruction,
    require_visual_medium,
    require_compatible_art_direction,
    resolve_visual_medium,
    validate_reference_tags,
)
from lib.lore import LoreFront
from lib.storyboard import Shot


class PromptCompilerTests(unittest.TestCase):
    def test_shot_override_wins_over_project_default(self) -> None:
        self.assertEqual(
            resolve_visual_medium(
                project_default="live_action",
                shot_overrides=["illustration"],
                fallback_text="真人",
            ),
            "2d_animation",
        )

    def test_project_default_wins_over_legacy_keyword_inference(self) -> None:
        self.assertEqual(
            resolve_visual_medium(
                project_default="live_action",
                fallback_text="cartoon sticker",
            ),
            "live_action",
        )

    def test_legacy_realistic_asset_infers_live_action(self) -> None:
        self.assertEqual(
            resolve_visual_medium(fallback_text="realistic red ball product photo"),
            "live_action",
        )

    def test_canonical_media_are_inferred_without_collapsing_animation(self) -> None:
        self.assertEqual(
            infer_visual_medium("stylized cinematic CG character sheet"),
            "3d_animation",
        )
        self.assertEqual(
            infer_visual_medium("hand-drawn cel animation character sheet"),
            "2d_animation",
        )
        self.assertEqual(
            infer_visual_medium("handcrafted claymation puppet"),
            "stop_motion",
        )

    def test_legacy_illustration_normalizes_to_2d(self) -> None:
        self.assertEqual(normalize_visual_medium("illustration"), "2d_animation")
        self.assertEqual(
            LoreFront(visual_medium="illustration").visual_medium,
            "2d_animation",
        )
        shot = Shot(
            id="S01-001",
            scene="S01",
            duration=8,
            prompt="A character crosses the room.",
            animatic_style="illustration",
            use_prev_last_frame_as_first=False,
        )
        self.assertEqual(shot.animatic_style, "2d_animation")

    def test_ambiguous_animation_is_rejected_when_declared(self) -> None:
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            require_visual_medium("animation")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            Shot(
                id="S01-001",
                scene="S01",
                duration=8,
                prompt="A character crosses the room.",
                animatic_style="animation",
                use_prev_last_frame_as_first=False,
            )

    def test_conflicting_2d_and_3d_text_infers_mixed(self) -> None:
        self.assertEqual(
            infer_visual_medium("live action host beside a 3D CG mascot"),
            "mixed",
        )

    def test_mixed_requires_local_boundary_instead_of_global_style(self) -> None:
        lore = {
            "visual_style": "live action host plus cartoon diagrams",
            "mood_anchor": "warm natural light",
            "palette": ["warm white", "candy accents"],
        }
        self.assertEqual(
            compatible_art_direction(lore, "mixed"),
            ["warm natural light", "palette: warm white, candy accents"],
        )

    def test_live_action_filters_illustration_only_mood(self) -> None:
        lore = {
            "visual_style": "rounded cartoon characters",
            "camera_language": "eye-level locked camera",
        }
        self.assertEqual(
            compatible_art_direction(lore, "live_action"),
            ["eye-level locked camera"],
        )

    def test_3d_medium_keeps_3d_style_and_filters_2d_style(self) -> None:
        lore = {
            "visual_style": "stylized cinematic CG animation",
            "camera_language": "hand-drawn cel animation framing",
            "mood_anchor": "deep indigo, moonlight silver",
        }
        self.assertEqual(
            compatible_art_direction(lore, "3d_animation"),
            ["stylized cinematic CG animation", "deep indigo, moonlight silver"],
        )

    def test_declared_2d_rejects_3d_art_direction(self) -> None:
        lore = {
            "visual_medium": "illustration",
            "visual_style": "stylized cinematic CG animation",
        }
        self.assertEqual(
            art_direction_conflicts(lore, "2d_animation"),
            [
                "visual_style declares ['3d_animation'] but visual_medium is "
                "2d_animation"
            ],
        )
        with self.assertRaisesRegex(ValueError, "visual medium conflict"):
            require_compatible_art_direction(lore, "2d_animation")

    def test_reference_tag_validation_accepts_repeated_valid_tags(self) -> None:
        validate_reference_tags(
            "@图片1: character\n@图片2: set\nShot follows @图片1",
            tag_prefix="@图片",
            reference_count=2,
        )

    def test_reference_tag_validation_rejects_missing_or_extra(self) -> None:
        with self.assertRaises(ValueError):
            validate_reference_tags(
                "@Image1: character\n@Image3: prop",
                tag_prefix="@Image",
                reference_count=2,
            )

    def test_rendering_instruction_is_explicit(self) -> None:
        self.assertIn("媒介边界", rendering_instruction("mixed", language="zh"))
        self.assertIn("boundary", rendering_instruction("mixed", language="en"))
        self.assertIn("3D CG", rendering_instruction("3d_animation"))
        self.assertIn("stop-motion", rendering_instruction("stop_motion"))

    def test_reference_treatment_is_medium_specific(self) -> None:
        self.assertIn(
            "3D CG",
            reference_treatment_instruction("3d_animation", subject="character"),
        )
        self.assertIn(
            "location layout",
            reference_treatment_instruction("2d_animation", subject="location"),
        )


if __name__ == "__main__":
    unittest.main()
