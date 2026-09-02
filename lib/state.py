"""Per-project / per-episode JSON state — agent and CLI both read/write this.

Filesystem layout:

    projects/<project_id>/
        lore.md                    # project-level world bible
        cast/                      # project-level shared cast
            <character_name>/
                cast.md            # soul card
                <reference>.png
                <voice>.mp3
        episode-<NNN>/             # one folder per episode
            script.md
            storyboard.json
            cast.json              # built per episode (project + episode cast merged)
            state.json
            shots_state.json
            cast/                  # episode-specific cast / NPCs
                <name>/
                    cast.md
                    <reference>.png
            cast_built/            # ASCII-renamed singletons + composite grids
            clips/
            frames/
            final/
            logs/
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.config import SETTINGS

# Episode-level subdirectories created on demand.
_EPISODE_SUBDIRS = ("clips", "frames", "final", "logs", "cast_built")


def normalize_episode_id(episode_id: str) -> str:
    """Return the canonical ``episode-<id>`` folder name.

    Rules:
      * If it already starts with ``episode-`` or ``episode_``, keep it.
      * Otherwise always prefix ``episode-``, including IDs containing
        punctuation such as ``anime-wan3.0``.

    This intentionally matches the deterministic scripts' episode-path
    handling so viewer/state helpers cannot resolve a different directory
    from render/storyboard/stitch commands.
    """
    ep = episode_id.strip()
    if not ep:
        raise ValueError("episode_id is empty")
    if ep.startswith("episode-") or ep.startswith("episode_"):
        return ep
    return f"episode-{ep}"


def project_dir(project_id: str) -> Path:
    """Project-level directory. Holds lore.md + project-shared cast/."""
    p = SETTINGS.projects_dir / project_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def episode_dir(project_id: str, episode_id: str) -> Path:
    """Episode-level directory. Holds storyboard / clips / frames / cast.json."""
    ep = normalize_episode_id(episode_id)
    p = project_dir(project_id) / ep
    p.mkdir(parents=True, exist_ok=True)
    for sub in _EPISODE_SUBDIRS:
        (p / sub).mkdir(exist_ok=True)
    return p


def list_episodes(project_id: str) -> list[str]:
    """Return canonical episode folder names that already exist on disk."""
    pdir = SETTINGS.projects_dir / project_id
    if not pdir.exists():
        return []
    out: list[str] = []
    for child in sorted(pdir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("episode-") or child.name.startswith("episode_"):
            out.append(child.name)
    return out


def read_json(
    project_id: str,
    name: str,
    *,
    episode_id: str | None = None,
    default: Any = None,
) -> Any:
    """Read JSON from project root (no episode) or episode dir (episode given)."""
    base = episode_dir(project_id, episode_id) if episode_id else project_dir(project_id)
    p = base / name
    if not p.exists():
        return default
    text = p.read_text(encoding="utf-8")
    if not text.strip():
        return default
    return json.loads(text)


def write_json(
    project_id: str,
    name: str,
    data: Any,
    *,
    episode_id: str | None = None,
) -> Path:
    base = episode_dir(project_id, episode_id) if episode_id else project_dir(project_id)
    p = base / name
    p.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return p


def merge_state(
    project_id: str,
    patch: dict,
    *,
    episode_id: str | None = None,
) -> dict:
    state = read_json(project_id, "state.json", episode_id=episode_id, default={}) or {}
    state.update(patch)
    write_json(project_id, "state.json", state, episode_id=episode_id)
    return state
