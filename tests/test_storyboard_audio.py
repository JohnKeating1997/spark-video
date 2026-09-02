from __future__ import annotations

import unittest

try:
    from pydantic import ValidationError
    from lib.storyboard import Storyboard
except ModuleNotFoundError:  # system Python may be dependency-free; uv runs these.
    ValidationError = None
    Storyboard = None


@unittest.skipIf(Storyboard is None, "run with uv so pydantic is available")
class StoryboardAudioTests(unittest.TestCase):
    def _shot(self, **overrides) -> dict:
        shot = {
            "id": "S01-001",
            "scene": "S01",
            "duration": 10,
            "kind": "t2v",
            "prompt": "A teacher gestures beside a plant.",
            "narrative_purpose": "Introduce the lesson through a clear gesture.",
            "use_prev_last_frame_as_first": False,
            "role": "drama",
            "speech_source": "post_tts",
            "speaker": "xiaoya",
            "speech_text": "Plants make their own food.",
            "visual_speech_mode": "voiceover",
        }
        shot.update(overrides)
        return shot

    def _presenter_storyboard(self, shot: dict | None = None, **overrides) -> dict:
        data = {
            "title": "lesson",
            "mode": "narration",
            "video_model": "wan3.0",
            "audio": {
                "mode": "presenter_voiceover",
                "presenter": "xiaoya",
                "voice": "xiaoya-voice",
                "model_audio_policy": "strip_all",
                "subtitle_mode": "off",
            },
            "shots": [shot or self._shot()],
        }
        data.update(overrides)
        return data

    def test_presenter_voiceover_has_one_explicit_voice(self) -> None:
        sb = Storyboard.model_validate(self._presenter_storyboard())
        self.assertEqual(sb.audio.voice, "xiaoya-voice")
        self.assertEqual(sb.shots[0].speech_source, "post_tts")

    def test_storyboard_defaults_to_720p(self) -> None:
        sb = Storyboard.model_validate(self._presenter_storyboard())
        self.assertEqual(sb.resolution, "720P")

    def test_presenter_voiceover_rejects_model_speech(self) -> None:
        shot = self._shot(
            speech_source="model",
            speech_text=None,
            visual_speech_mode="on_camera",
        )
        with self.assertRaises(ValidationError):
            Storyboard.model_validate(self._presenter_storyboard(shot))

    def test_presenter_voiceover_rejects_silent_shot(self) -> None:
        shot = self._shot(
            speech_source="none",
            speech_text=None,
            visual_speech_mode="none",
        )
        with self.assertRaises(ValidationError):
            Storyboard.model_validate(self._presenter_storyboard(shot))

    def test_presenter_voiceover_rejects_per_shot_voice_change(self) -> None:
        shot = self._shot(narrator_voice="different-voice")
        with self.assertRaises(ValidationError):
            Storyboard.model_validate(self._presenter_storyboard(shot))

    def test_wan30_long_shot_requires_contiguous_beats(self) -> None:
        shot = self._shot(
            duration=24,
            long_take_reason=(
                "The uninterrupted transformation must preserve spatial "
                "continuity and would lose its reveal if cut."
            ),
            beats=[
                {"start_s": 0, "end_s": 6, "action": "establish"},
                {"start_s": 6, "end_s": 18, "action": "demonstrate"},
                {"start_s": 18, "end_s": 24, "action": "resolve"},
            ],
        )
        sb = Storyboard.model_validate(self._presenter_storyboard(shot))
        self.assertEqual(sb.shots[0].duration, 24)

    def test_long_shot_has_no_duration_based_beat_count(self) -> None:
        shot = self._shot(
            duration=24,
            long_take_reason="One sustained performance whose tension depends on no cut.",
            beats=[
                {"start_s": 0, "end_s": 24, "action": "sustain the performance"},
            ],
        )
        sb = Storyboard.model_validate(self._presenter_storyboard(shot))
        self.assertEqual(len(sb.shots[0].beats), 1)

    def test_long_shot_requires_reason_not_a_beat_quota(self) -> None:
        shot = self._shot(
            duration=20,
            beats=[{"start_s": 0, "end_s": 20, "action": "continuous action"}],
        )
        with self.assertRaises(ValidationError):
            Storyboard.model_validate(self._presenter_storyboard(shot))

    def test_wan27_rejects_duration_over_15(self) -> None:
        shot = self._shot(
            duration=18,
            long_take_reason="A continuous reveal.",
            beats=[
                {"start_s": 0, "end_s": 9, "action": "establish"},
                {"start_s": 9, "end_s": 18, "action": "resolve"},
            ],
        )
        with self.assertRaises(ValidationError):
            Storyboard.model_validate(
                self._presenter_storyboard(shot, video_model="wan2.7")
            )

    def test_legacy_narration_infers_hybrid_audio(self) -> None:
        data = {
            "title": "legacy",
            "mode": "narration",
            "shots": [{
                "id": "S01-001",
                "scene": "S01",
                "duration": 5,
                "prompt": "Leaves move in sunlight.",
                "role": "narration",
                "narration_text": "Plants use light.",
            }],
        }
        sb = Storyboard.model_validate(data)
        self.assertEqual(sb.audio.mode, "hybrid")
        self.assertEqual(sb.shots[0].speech_source, "post_tts")
        self.assertEqual(sb.shots[0].speech_text, "Plants use light.")


if __name__ == "__main__":
    unittest.main()
