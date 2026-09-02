"""Cross-platform command helpers for spark-video scripts."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


IS_WINDOWS = os.name == "nt"


def script_cmd(repo_root: Path, script_name: str) -> list[str]:
    """Return a subprocess command prefix for a repo-local script.

    Unix-like systems use executable scripts directly. Native Windows uses
    PowerShell wrappers so callers do not need Bash, WSL, or MSYS.
    """
    scripts_dir = Path(repo_root) / "scripts"
    if IS_WINDOWS:
        ps1 = scripts_dir / f"{script_name}.ps1"
        if not ps1.exists():
            raise FileNotFoundError(f"Windows script wrapper not found: {ps1}")
        return [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps1),
        ]

    sh = scripts_dir / script_name
    if not sh.exists():
        raise FileNotFoundError(f"script wrapper not found: {sh}")
    return [str(sh)]


def bl_cmd(repo_root: Path) -> list[str]:
    """Return the logging bl wrapper command for this platform."""
    return script_cmd(repo_root, "bl")


def wan_cmd(repo_root: Path) -> list[str]:
    """Return a wan command prefix that also supports npm ``wan.cmd`` shims."""
    if IS_WINDOWS:
        return script_cmd(repo_root, "wan")
    return ["wan"]


def wan_config(repo_root: Path) -> dict[str, Any]:
    """Return the effective wan CLI config without exposing credentials."""
    try:
        proc = subprocess.run(
            wan_cmd(repo_root) + ["config", "show", "--output", "json"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0:
        return {}

    text = proc.stdout.strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def active_wan_site(repo_root: Path, *, default: str = "intl") -> str:
    """Return ``cn`` or ``intl``; unknown config defaults to international."""
    site = str(wan_config(repo_root).get("site") or "").strip().lower()
    return site if site in {"cn", "intl"} else default


def wan_media_tag(kind: str, index: int, *, site: str) -> str:
    """Return the exact Wan prompt tag for one ordered reference asset."""
    labels = {
        "cn": {"image": "图片", "video": "视频", "audio": "音频", "file": "文件"},
        "intl": {"image": "Image", "video": "Video", "audio": "Audio", "file": "File"},
    }
    normalized_site = site if site in labels else "intl"
    if kind not in labels[normalized_site]:
        raise ValueError(f"unsupported Wan media kind: {kind!r}")
    if index < 1:
        raise ValueError("Wan media tag index must start at 1")
    return f"@{labels[normalized_site][kind]}{index}"
