from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.providers import wan_cli


class WanCliProviderCommandTests(unittest.TestCase):
    def build_result(self, **overrides):
        values = {
            "model": "wan3.0",
            "kind": "t2v",
            "prompt": "A continuous shot",
            "images": [],
            "videos": [],
            "audios": [],
            "first_frame": None,
            "duration": 12,
            "resolution": "720P",
            "ratio": "16:9",
            "temp_dir": "/tmp/wan-provider-test",
            "timeout": 30,
            "audio_output": True,
        }
        values.update(overrides)
        with patch.object(wan_cli, "_active_wan_site", return_value="cn"):
            return wan_cli._build_wan_command(Path.cwd(), **values)

    def build(self, **overrides):
        return self.build_result(**overrides)[0]

    def test_wan30_plain_text_uses_omni(self) -> None:
        cmd = self.build(audio_output=False)
        self.assertIn("omni2video", cmd)
        self.assertIn("wan3.0", cmd)
        self.assertIn("--audio-output=false", cmd)

    def test_wan30_local_frame_upload_uses_omni_namespace(self) -> None:
        self.assertEqual(
            wan_cli._upload_task_type(model="wan3.0", kind="r2v"),
            "omni_video_generate",
        )

    def test_wan30_reference_shot_uses_omni(self) -> None:
        cmd = self.build(kind="r2v", images=["https://example.com/cast.png"])
        self.assertIn("omni2video", cmd)
        self.assertIn("--images", cmd)

    def test_wan30_opening_frame_stays_on_omni(self) -> None:
        cmd, prompt = self.build_result(
            kind="i2v",
            first_frame="https://example.com/start.png",
            duration=30,
            audio_output=False,
        )
        self.assertIn("omni2video", cmd)
        self.assertNotIn("frame2video", cmd)
        self.assertIn("--images", cmd)
        self.assertIn("https://example.com/start.png", cmd)
        self.assertIn("--audio-output=false", cmd)
        self.assertIn("@图片1 是目标开场构图", prompt)

    def test_wan30_opening_and_ending_frames_are_prompt_described(self) -> None:
        cmd, prompt = self.build_result(
            kind="i2v",
            images=["https://example.com/cast.png"],
            first_frame="https://example.com/start.png",
            last_frame="https://example.com/end.png",
        )
        self.assertIn("omni2video", cmd)
        image_values = cmd[cmd.index("--images") + 1]
        self.assertEqual(
            image_values,
            ",".join([
                "https://example.com/cast.png",
                "https://example.com/start.png",
                "https://example.com/end.png",
            ]),
        )
        self.assertIn("@图片2 是目标开场构图", prompt)
        self.assertIn("@图片3 是目标结束构图", prompt)

    def test_wan30_audio_reference_uses_omni(self) -> None:
        cmd = self.build(
            kind="r2v",
            images=["https://example.com/cast.png"],
            audios=["https://example.com/voice.mp3"],
        )
        self.assertIn("omni2video", cmd)
        self.assertIn("--audios", cmd)

    def test_wan27_image_continuity_uses_frame2video(self) -> None:
        cmd = self.build(
            model="wan2.7",
            kind="i2v",
            images=["https://example.com/start.png"],
            duration=8,
        )
        self.assertIn("frame2video", cmd)
        self.assertIn("--first-frame", cmd)
        self.assertNotIn("image2video", cmd)
        self.assertIn("wan2.7", cmd)

    def test_wan30_video_reference_reduces_output_duration_ceiling(self) -> None:
        with patch.object(
            wan_cli,
            "_full_local_video_ranges",
            return_value=(["0:5"], 5.0),
        ):
            with self.assertRaisesRegex(ValueError, "30 - selected video seconds"):
                self.build(videos=["/tmp/reference.mp4"], duration=26)


if __name__ == "__main__":
    unittest.main()
