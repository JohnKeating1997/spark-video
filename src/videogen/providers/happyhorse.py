"""HappyHorse 1.0 video provider.

Capability differences from Wan that drive the build logic here:

* r2v accepts only ``reference_image`` (1~9 images). It does NOT accept
  ``first_frame`` for chain bridging, and it does NOT accept
  ``reference_voice`` for character TTS. When a chained r2v shot is asked
  for, we **auto-demote** it to i2v (kind="i2v" effectively) so the chain
  keeps working — the chain takes precedence over the multi-character
  reference because losing continuity is worse than losing one character's
  visual lock for one shot.

* i2v ignores ``ratio`` (output ratio is derived from the first frame).

* t2v / r2v ratio default is ``1080P``; we still pass the storyboard's
  resolution explicitly to be deterministic.

* No ``prompt_extend`` parameter.
* No ``negative_prompt`` field on input.
* ``watermark`` defaults to true upstream — we always pass ``false``.
* Duration minimum is 3s (vs 2s for Wan); we clamp on build.
"""
from __future__ import annotations

from typing import Any

from rich.console import Console

from .base import BuildResult, Feature, ShotKind, VideoProvider

console = Console()


class HappyHorseProvider(VideoProvider):
    name = "happyhorse"

    models: dict[ShotKind, str] = {
        "t2v": "happyhorse-1.0-t2v",
        "i2v": "happyhorse-1.0-i2v",
        "r2v": "happyhorse-1.0-r2v",
    }

    duration_max: dict[ShotKind, int] = {"t2v": 15, "i2v": 15, "r2v": 15}
    duration_min: dict[ShotKind, int] = {"t2v": 3, "i2v": 3, "r2v": 3}

    # Conspicuously empty — HappyHorse is the constrained provider.
    features: frozenset[Feature] = frozenset()

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

        # Auto-demote r2v + chain → i2v, since HappyHorse r2v cannot accept
        # first_frame. We prefer continuity over multi-image reference for
        # this shot. Director can pin kind=r2v explicitly to skip this if
        # they really want; in that case we drop the chain frame instead.
        if (
            kind == "r2v"
            and prev_last_frame_url
            and shot.use_prev_last_frame_as_first
        ):
            kind = "i2v"
            warnings.append(
                f"{shot.id}: HappyHorse r2v has no first_frame; auto-demoted "
                f"to i2v for this shot to keep the chain. Reference images "
                f"are dropped — character lock relies on the previous shot's "
                f"last frame instead."
            )

        media: list[dict] = []
        char_index = {c["name"]: c for c in cast_data["characters"]}
        skipped_voice: list[str] = []

        if kind == "r2v":
            for char_name in shot.characters:
                c = char_index.get(char_name)
                if not c:
                    raise ValueError(
                        f"shot {shot.id} references unknown cast {char_name!r}"
                    )
                media.append({
                    "type": "reference_image",
                    "url": c["image_url"],
                })
                if c.get("audio_url"):
                    skipped_voice.append(char_name)
            if not media:
                raise ValueError(
                    f"r2v shot {shot.id} needs at least one character with a "
                    f"reference_image; HappyHorse r2v requires media[]."
                )

        elif kind == "i2v":
            if not prev_last_frame_url:
                raise ValueError(
                    f"i2v shot {shot.id} needs a previous last frame; set "
                    f"use_prev_last_frame_as_first=true on a chained predecessor."
                )
            media.append({"type": "first_frame", "url": prev_last_frame_url})

        # t2v: no media

        if skipped_voice:
            warnings.append(
                f"{shot.id}: HappyHorse r2v has no reference_voice; ignored "
                f"audio for cast {skipped_voice}. Add a TTS pass post-render "
                f"if you need spoken dialog."
            )

        if shot.negative_prompt:
            warnings.append(
                f"{shot.id}: HappyHorse has no negative_prompt; "
                f"shot.negative_prompt is ignored."
            )

        input_obj: dict[str, Any] = {"prompt": prompt}
        if media:
            input_obj["media"] = media

        # Clamp duration to provider floor (3s for HappyHorse).
        duration = max(shot.duration, self.duration_min[kind])
        if duration != shot.duration:
            warnings.append(
                f"{shot.id}: duration {shot.duration}s clamped to "
                f"{duration}s (HappyHorse minimum)."
            )

        parameters: dict[str, Any] = {
            "resolution": storyboard.resolution,
            "duration": duration,
            "watermark": False,
        }
        # i2v ignores ratio — only set it for t2v / r2v.
        if kind != "i2v":
            parameters["ratio"] = storyboard.ratio
        if shot.seed is not None:
            parameters["seed"] = shot.seed

        for w in warnings:
            console.print(f"[yellow]·[/] {w}")

        return BuildResult(
            model=self.model_for(kind),
            input=input_obj,
            parameters=parameters,
            effective_kind=kind,
            warnings=warnings,
        )
