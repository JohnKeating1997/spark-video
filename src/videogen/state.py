"""Per-project JSON state — agent and CLI both read/write this."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import SETTINGS


def project_dir(project_id: str) -> Path:
    p = SETTINGS.projects_dir / project_id
    p.mkdir(parents=True, exist_ok=True)
    (p / "clips").mkdir(exist_ok=True)
    (p / "frames").mkdir(exist_ok=True)
    (p / "final").mkdir(exist_ok=True)
    (p / "logs").mkdir(exist_ok=True)
    return p


def _path(project_id: str, name: str) -> Path:
    return project_dir(project_id) / name


def read_json(project_id: str, name: str, default: Any = None) -> Any:
    p = _path(project_id, name)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(project_id: str, name: str, data: Any) -> Path:
    p = _path(project_id, name)
    p.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return p


def merge_state(project_id: str, patch: dict) -> dict:
    state = read_json(project_id, "state.json", default={}) or {}
    state.update(patch)
    write_json(project_id, "state.json", state)
    return state
