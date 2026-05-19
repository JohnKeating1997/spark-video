# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
bl provider — subprocess wrapper around `./scripts/bl video generate|ref|edit`.

Covers happyhorse-1.0-{t2v,i2v,r2v} and wan2.6-{t2v,r2v}. Wan 2.7 features
(precise first_frame chain bridging, negative_prompt, prompt_extend) require
the dashscope_wan27 provider — see scripts/providers/dashscope_wan27.py.

Public API:
    render(kind, prompt, media, voice, duration, out_path, extra) -> dict
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

# Allow `from lib...` imports when invoked as a script.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent))


_REPO_ROOT = Path(__file__).resolve().parents[2]
_BL_WRAPPER = _REPO_ROOT / "scripts" / "bl"


def _bl_cmd() -> list[str]:
    """Always invoke the logging wrapper, not raw bl."""
    if not _BL_WRAPPER.exists():
        raise RuntimeError(
            f"{_BL_WRAPPER} not found. Did you forget to chmod +x scripts/bl?"
        )
    return [str(_BL_WRAPPER)]


def _run(cmd: list[str], *, timeout: int) -> subprocess.CompletedProcess:
    """Run a subprocess, raise on non-zero, return CompletedProcess."""
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(_REPO_ROOT),
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"bl exited {proc.returncode}\nCMD: {' '.join(cmd)}\n"
            f"STDERR:\n{proc.stderr[-2000:]}"
        )
    return proc


def render(
    *,
    kind: Literal["t2v", "i2v", "r2v"],
    prompt: str,
    media: list[Path] | None = None,
    voice: Path | None = None,
    duration: int,
    out_path: Path,
    extra: dict | None = None,
) -> dict:
    """
    Submit a video render via bl and wait for completion.

    Returns: {video_path, model, elapsed_s}
    Raises:  RuntimeError on bl failure.
    """
    media = media or []
    extra = extra or {}
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Bl's t2v floor is 5s, ceiling 10–15s depending on the kind.
    # Clamp; caller (render_shot.py) already checks but defense in depth.
    duration = max(2, min(15, int(duration)))

    cmd = _bl_cmd()
    if kind == "t2v":
        # bl video generate without --image
        cmd += ["video", "generate", "--prompt", prompt, "--duration", str(duration)]
    elif kind == "i2v":
        # bl video generate auto-switches to i2v when --image is supplied
        if not media:
            raise ValueError("i2v requires at least one media (first frame)")
        cmd += [
            "video", "generate",
            "--prompt", prompt,
            "--image", str(media[0]),
            "--duration", str(duration),
        ]
    elif kind == "r2v":
        cmd += ["video", "ref", "--prompt", prompt, "--duration", str(duration)]
        for m in media:
            cmd += ["--image", str(m)]
        if voice is not None:
            cmd += ["--image-voice", str(voice)]
    else:
        raise ValueError(f"unknown kind: {kind}")

    # Common flags
    cmd += ["--download", str(out_path)]
    cmd += ["--resolution", extra.get("resolution", "1080P")]
    if "ratio" in extra:
        cmd += ["--ratio", str(extra["ratio"])]
    if "seed" in extra and extra["seed"] is not None:
        cmd += ["--seed", str(extra["seed"])]
    if extra.get("model"):
        cmd += ["--model", str(extra["model"])]

    # JSON output for parseability
    cmd = [cmd[0]] + ["--output", "json"] + cmd[1:]

    started = time.time()
    timeout_s = int(os.environ.get("SPARK_VIDEO_RENDER_TIMEOUT_S", "900"))
    proc = _run(cmd, timeout=timeout_s)
    elapsed = time.time() - started

    if not out_path.exists():
        raise RuntimeError(
            f"bl returned exit 0 but no video at {out_path}\nSTDOUT:\n{proc.stdout[-2000:]}"
        )

    # Best-effort: extract task_id / model from bl's JSON stdout
    model = extra.get("model") or _infer_default_model(kind)
    try:
        data = json.loads(proc.stdout)
        if isinstance(data, dict):
            model = data.get("model", model)
    except (json.JSONDecodeError, ValueError):
        pass

    return {
        "video_path": str(out_path),
        "model": model,
        "elapsed_s": round(elapsed, 2),
    }


def _infer_default_model(kind: str) -> str:
    return {
        "t2v": "happyhorse-1.0-t2v",
        "i2v": "happyhorse-1.0-i2v",
        "r2v": "happyhorse-1.0-r2v",
    }.get(kind, "happyhorse-1.0-r2v")
