"""Wan 2.7 video provider.

Wan supports the richest feature set: r2v with first_frame chain bridging,
reference_voice for character TTS, prompt_extend, and negative_prompt.
"""
from __future__ import annotations

from typing import Any

from .base import BuildResult, Feature, ShotKind, VideoProvider


class WanProvider(VideoProvider):
    name = "wan"

    models: dict[ShotKind, str] = {
        "t2v": "wan2.7-t2v-2026-04-25",
        "i2v": "wan2.7-i2v-2026-04-25",
        "r2v": "wan2.7-r2v",
    }

    duration_max: dict[ShotKind, int] = {"t2v": 15, "i2v": 15, "r2v": 15}
    duration_min: dict[ShotKind, int] = {"t2v": 2, "i2v": 2, "r2v": 2}

    features: frozenset[Feature] = frozenset({
        "reference_voice",
        "first_frame_in_r2v",
        "prompt_extend",
        "negative_prompt",
        "i2v_ratio",
    })

    def build_request(
        self,
        shot,
        *,
        storyboard,
        prompt: str,
        cast_data: dict,
        prev_last_frame_url: str | None,
    ) -> BuildResult:
        kind: ShotKind = shot.kind
        warnings: list[str] = []
        media: list[dict] = []
        char_index = {c["name"]: c for c in cast_data["characters"]}

        if kind == "r2v":
            for char_name in shot.characters:
                c = char_index.get(char_name)
                if not c:
                    raise ValueError(
                        f"shot {shot.id} references unknown cast {char_name!r}"
                    )
                entry: dict[str, Any] = {
                    "type": "reference_image",
                    "url": c["image_url"],
                }
                if c.get("audio_url"):
                    entry["reference_voice"] = c["audio_url"]
                media.append(entry)
            if prev_last_frame_url and shot.use_prev_last_frame_as_first:
                media.append({"type": "first_frame", "url": prev_last_frame_url})

        elif kind == "i2v":
            if not prev_last_frame_url:
                raise ValueError(
                    f"i2v shot {shot.id} needs a previous last frame; "
                    f"set use_prev_last_frame_as_first=true on a chained "
                    f"predecessor or change kind to t2v / r2v."
                )
            media.append({"type": "first_frame", "url": prev_last_frame_url})

        # t2v: no media

        input_obj: dict[str, Any] = {"prompt": prompt}
        if shot.negative_prompt:
            input_obj["negative_prompt"] = shot.negative_prompt
        if media:
            input_obj["media"] = media

        parameters: dict[str, Any] = {
            "resolution": storyboard.resolution,
            "ratio": storyboard.ratio,
            "duration": shot.duration,
            "prompt_extend": True,
            "watermark": False,
        }
        if shot.seed is not None:
            parameters["seed"] = shot.seed

        return BuildResult(
            model=self.model_for(kind),
            input=input_obj,
            parameters=parameters,
            effective_kind=kind,
            warnings=warnings,
        )
