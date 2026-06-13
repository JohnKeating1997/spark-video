"""Cross-platform command helpers for spark-video scripts."""
from __future__ import annotations

import os
from pathlib import Path


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
