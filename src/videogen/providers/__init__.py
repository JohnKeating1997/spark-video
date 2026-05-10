"""Video provider abstraction layer.

Decouples the rest of the pipeline (storyboard schema, render driver, director
skill) from any specific DashScope video model family. Each provider knows:

  * How a generic shot ``kind`` (``t2v`` / ``i2v`` / ``r2v``) maps to one of
    its concrete model names.
  * How to build the request body for that model (input.media, parameters).
  * Which features it supports (``reference_voice`` / ``first_frame_in_r2v`` /
    ``prompt_extend`` / ``negative_prompt`` / ``i2v_ratio``).
  * Per-kind duration ceilings + floors.
  * The async submit + poll lifecycle (currently identical for all DashScope
    video providers, but encapsulated so per-vendor headers can be added).

The producer / director picks a provider via:

  * ``Storyboard.provider`` (per-episode, written by ``scene compile``)
  * ``--provider`` CLI flag (per-run override)
  * ``VIDEOGEN_VIDEO_PROVIDER`` env var (workspace default)
  * Built-in default ``"happyhorse"``.
"""
from __future__ import annotations

from .base import (
    Feature,
    ProviderName,
    ShotKind,
    VideoProvider,
)
from .happyhorse import HappyHorseProvider
from .registry import get_provider, list_providers
from .wan import WanProvider

__all__ = [
    "Feature",
    "HappyHorseProvider",
    "ProviderName",
    "ShotKind",
    "VideoProvider",
    "WanProvider",
    "get_provider",
    "list_providers",
]
