"""Wan 2.7 video provider.

Wan supports the richest feature set: r2v with first_frame chain bridging,
reference_voice for character TTS, prompt_extend, and negative_prompt.
"""
from __future__ import annotations

from typing import Any

from .. import bgm as bgm_mod
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
        scene=None,
        movie_set_data: dict | None = None,
        prop_data: dict | None = None,
    ) -> BuildResult:
        kind: ShotKind = shot.kind
        warnings: list[str] = []
        media: list[dict] = []
        char_index = {c["name"]: c for c in cast_data["characters"]}
        set_index = {
            s["name"]: s for s in (movie_set_data or {}).get("sets", [])
        }
        prop_index = {
            p["name"]: p for p in (prop_data or {}).get("props", [])
        }

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
            # Lock the location with a set reference image, after the cast.
            set_url = _resolve_set_image_url(shot, scene, set_index, warnings)
            if set_url:
                media.append({"type": "reference_image", "url": set_url})
            # Lock key props after cast + set.
            for prop_name in shot.props:
                purl = _resolve_prop_image_url(shot, prop_name, prop_index, warnings)
                if purl:
                    media.append({"type": "reference_image", "url": purl})
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

        # If the episode forbids in-clip BGM, weave the directive into both
        # the prompt (steers generation) and the negative_prompt (banlist).
        effective_prompt = prompt
        negative_prompt = shot.negative_prompt or ""
        if getattr(storyboard, "bgm", None) and storyboard.bgm.forbid_model_bgm:
            directive = bgm_mod.forbid_directive()
            if directive not in effective_prompt:
                effective_prompt = f"{effective_prompt} {directive}".strip()
            neg_terms = bgm_mod.forbid_negative_terms()
            if neg_terms not in negative_prompt:
                negative_prompt = (
                    f"{negative_prompt}, {neg_terms}" if negative_prompt else neg_terms
                )

        input_obj: dict[str, Any] = {"prompt": effective_prompt}
        if negative_prompt:
            input_obj["negative_prompt"] = negative_prompt
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


def _resolve_set_image_url(
    shot,
    scene,
    set_index: dict[str, dict],
    warnings: list[str],
) -> str | None:
    """Resolve set_id → uploaded image_url.

    Precedence (per-shot override beats scene-level default):
      shot.set_id  (None = inherit; ""  = explicit "no set")
        > scene.set_id

    Warns (never raises) when the resolved name is not in movie_set.json.
    """
    set_id = _effective_set_id(shot, scene)
    if not set_id:
        return None
    s = set_index.get(set_id)
    if not s:
        warnings.append(
            f"{shot.id}: set_id={set_id!r} has no folder in movie_set.json "
            f"— set reference image skipped. Add a folder under "
            f"projects/<id>/movie-set/ or projects/<id>/<episode>/movie-set/ "
            f"and re-run `videogen set init`."
        )
        return None
    url = s.get("image_url")
    if not url:
        warnings.append(
            f"{shot.id}: set {set_id!r} has no image_url (likely "
            f"`set init --no-upload`); set reference image skipped."
        )
    return url


def _resolve_prop_image_url(
    shot,
    prop_name: str,
    prop_index: dict[str, dict],
    warnings: list[str],
) -> str | None:
    """Resolve a single prop name → uploaded image_url.

    Warns (never raises) when the prop name isn't in props.json.
    """
    p = prop_index.get(prop_name)
    if not p:
        warnings.append(
            f"{shot.id}: prop {prop_name!r} has no folder in props.json — "
            f"reference image skipped. Add a folder under "
            f"projects/<id>/props/ or projects/<id>/<episode>/props/ and "
            f"re-run `videogen prop init`."
        )
        return None
    url = p.get("image_url")
    if not url:
        warnings.append(
            f"{shot.id}: prop {prop_name!r} has no image_url (likely "
            f"`prop init --no-upload`); reference image skipped."
        )
    return url


def _effective_set_id(shot, scene) -> str | None:
    """Resolve the active set_id for one shot, honouring the per-shot
    override semantics:

      - shot.set_id is None   → inherit scene.set_id
      - shot.set_id == ""     → explicit opt-out, no set even if scene has one
      - shot.set_id == "x"    → use 'x' regardless of scene.set_id
    """
    shot_set = getattr(shot, "set_id", None)
    if shot_set is not None:
        return shot_set or None  # "" → None
    if scene is None:
        return None
    return getattr(scene, "set_id", None) or None
