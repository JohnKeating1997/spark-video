from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts import render_shot


class RenderPromptContractTests(unittest.TestCase):
    def test_model_bgm_is_forbidden_when_storyboard_has_no_bgm_config(self) -> None:
        with TemporaryDirectory() as tmp:
            ep_dir = Path(tmp)
            (ep_dir / "storyboard.json").write_text(
                '{"shots": []}', encoding="utf-8"
            )
            self.assertTrue(render_shot._forbid_model_bgm(ep_dir))

    def test_model_bgm_can_be_explicitly_allowed(self) -> None:
        with TemporaryDirectory() as tmp:
            ep_dir = Path(tmp)
            (ep_dir / "storyboard.json").write_text(
                '{"bgm": {"forbid_model_bgm": false}}', encoding="utf-8"
            )
            self.assertFalse(render_shot._forbid_model_bgm(ep_dir))

    def test_long_shot_keeps_wan_music_with_fades(self) -> None:
        with TemporaryDirectory() as tmp:
            ep_dir = Path(tmp)
            (ep_dir / "storyboard.json").write_text(
                '{"shots": [{"id": "S01-001", "duration": 20, "speech_source": "model"}]}',
                encoding="utf-8",
            )
            self.assertFalse(render_shot._forbid_model_bgm(ep_dir, "S01-001"))
            shot = {"duration": 20}
            directive = render_shot._long_shot_music_directive(shot, zh=False)
            self.assertIn("fade it in over about 2 seconds", directive)
            self.assertIn("fade it out over about 3 seconds", directive)

    def test_program_bgm_disables_long_shot_model_music(self) -> None:
        with TemporaryDirectory() as tmp:
            ep_dir = Path(tmp)
            (ep_dir / "storyboard.json").write_text(
                '{"bgm": {"enabled": true, "mode": "global"}, "shots": '
                '[{"id": "S01-001", "duration": 20, "speech_source": "model"}]}',
                encoding="utf-8",
            )
            self.assertTrue(render_shot._forbid_model_bgm(ep_dir, "S01-001"))

    def test_bgm_config_defaults_to_forbid_model_music(self) -> None:
        from lib.storyboard import BGMConfig

        config = BGMConfig()
        self.assertTrue(config.forbid_model_bgm)
        self.assertEqual(config.fade_in_s, 0.5)
        self.assertEqual(config.fade_out_s, 2.0)

    def test_non_continuous_transition_preserves_only_declared_attributes(self) -> None:
        shot = {
            "speech_source": "none",
            "duration": 5,
            "transition_from_previous": {
                "type": "shot_reverse_shot",
                "preserve": ["eyeline", "lighting"],
                "allow_change": ["camera_angle"],
            },
        }
        with (
            patch.object(render_shot, "_read_lore_style", return_value={}),
            patch.object(render_shot, "_storyboard_shot", return_value=shot),
            patch.object(render_shot, "_forbid_model_bgm", return_value=False),
        ):
            prompt = render_shot._structured_video_prompt(
                ep_dir=Path("/tmp/unused"),
                shot_id="S01-002",
                prompt="The listener answers.",
                voice=None,
            )

        self.assertIn("Transition from previous:", prompt)
        self.assertIn("type: shot_reverse_shot", prompt)
        self.assertIn("Preserve: eyeline, lighting", prompt)
        self.assertIn("Do not copy the preceding final frame", prompt)

    def test_short_choreographed_shot_keeps_optional_micro_timeline(self) -> None:
        shot = {
            "speech_source": "none",
            "visual_speech_mode": "none",
            "allow_generated_text": False,
            "duration": 5,
            "camera_path": "极低机位稳定后撤，最后略微抬升。",
            "end_composition": "人物停在略低机位中近景。",
            "beats": [
                {"start_s": 0, "end_s": 2, "action": "靴底压实焦土"},
                {"start_s": 2, "end_s": 5, "action": "人物继续逼近并停稳"},
            ],
        }
        with (
            patch.object(render_shot, "_read_lore_style", return_value={}),
            patch.object(render_shot, "_storyboard_shot", return_value=shot),
            patch.object(render_shot, "_forbid_model_bgm", return_value=False),
        ):
            prompt = render_shot._structured_video_prompt(
                ep_dir=Path("/tmp/unused"),
                shot_id="S01-001",
                prompt="骑士以沉重而克制的步伐持续逼近。",
                voice=None,
                prompt_language="zh",
            )

        self.assertIn("micro shot · 2-5s", prompt)
        self.assertIn("0-2s: 靴底压实焦土", prompt)
        self.assertIn("2-5s: 人物继续逼近并停稳", prompt)

    def test_post_tts_long_shot_keeps_voice_out_and_injects_beats(self) -> None:
        shot = {
            "speech_source": "post_tts",
            "visual_speech_mode": "voiceover",
            "allow_generated_text": False,
            "duration": 20,
            "camera_path": "中景平视起步，缓慢推进并向右小幅环绕，停在叶片特写。",
            "end_composition": "叶片占画面右侧三分之一，教师虚化留在左后方。",
            "beats": [
                {"start_s": 0, "end_s": 10, "action": "叶片迎向阳光"},
                {"start_s": 10, "end_s": 20, "action": "水分沿叶脉移动"},
            ],
        }
        with (
            patch.object(render_shot, "_read_lore_style", return_value={}),
            patch.object(render_shot, "_storyboard_shot", return_value=shot),
            patch.object(render_shot, "_forbid_model_bgm", return_value=True),
        ):
            prompt = render_shot._structured_video_prompt(
                ep_dir=Path("/tmp/unused"),
                shot_id="S01-001",
                prompt="教师用手势展示叶片结构。",
                voice=None,
                reference_image_map="参考图映射：\n图1：教师角色定妆。",
                prompt_language="zh",
            )

        self.assertIn("参考契约：", prompt)
        self.assertIn("复杂度预算：", prompt)
        self.assertIn("0-10s: 叶片迎向阳光", prompt)
        self.assertIn("不要生成人物对白、旁白或可辨识的说话声", prompt)
        self.assertIn("不要生成字幕", prompt)
        self.assertIn("摄影机路径：", prompt)
        self.assertIn("结束构图：", prompt)
        self.assertLess(prompt.index("镜头："), prompt.index("时序动作："))
        self.assertLess(prompt.index("时序动作："), prompt.index("摄影机路径："))
        self.assertLess(prompt.index("摄影机路径："), prompt.index("结束构图："))
        self.assertLess(prompt.index("结束构图："), prompt.index("音频："))


if __name__ == "__main__":
    unittest.main()
