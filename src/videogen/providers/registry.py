"""Provider registry — single entry point for picking a video provider.

Resolution order (most specific wins):
  1. explicit ``name`` argument (e.g. CLI ``--provider``)
  2. ``Storyboard.provider`` (per-episode, written by ``scene compile``)
  3. ``VIDEOGEN_VIDEO_PROVIDER`` env var
  4. built-in default ``"happyhorse"``
"""
from __future__ import annotations

from ..config import SETTINGS
from .base import ProviderName, VideoProvider
from .happyhorse import HappyHorseProvider
from .wan import WanProvider

_REGISTRY: dict[str, type[VideoProvider]] = {
    "wan": WanProvider,
    "happyhorse": HappyHorseProvider,
}

_BUILTIN_DEFAULT: ProviderName = "happyhorse"


def list_providers() -> list[str]:
    return sorted(_REGISTRY)


def get_provider(name: str | None = None) -> VideoProvider:
    """Return a fresh provider instance.

    ``name`` may be ``None`` (use env / default) or any registered name.
    Raises ``ValueError`` for unknown names with a helpful message.
    """
    chosen = (name or SETTINGS.video_provider or _BUILTIN_DEFAULT).strip().lower()
    cls = _REGISTRY.get(chosen)
    if cls is None:
        raise ValueError(
            f"unknown video provider {chosen!r}; "
            f"valid: {list_providers()}. "
            f"Set VIDEOGEN_VIDEO_PROVIDER or pass --provider."
        )
    return cls()
