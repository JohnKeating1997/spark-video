# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
bl provider — subprocess wrapper around `./scripts/bl video generate|ref|edit`.

Covers happyhorse-1.0-{t2v,i2v,r2v} and wan2.6-{t2v,r2v}. Use the wan-cli
provider with `VIDEOGEN_WAN_VIDEO_MODEL=wan2.7` for Wan 2.7 generation.

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


# bl stderr substrings that indicate a transient network/socket hiccup the
# caller can safely retry. Keep narrow — model-side validation errors must
# NOT retry (they'll fail identically and waste quota).
_TRANSIENT_PATTERNS = (
    "EBADF",
    "Network request failed",
    "Connection reset",
    "ConnectionError",
    "ConnectionResetError",
    "ConnectionAbortedError",
    "RemoteDisconnected",
    "Temporary failure in name resolution",
    "timed out",
    "Read timed out",
    "502 Bad Gateway",
    "503 Service Unavailable",
    "504 Gateway Time-out",
)


def _is_transient(stderr: str) -> bool:
    return any(p in stderr for p in _TRANSIENT_PATTERNS)


def _clamp_duration(duration: int) -> int:
    """Clamp to the HappyHorse duration range exposed by the bl provider."""
    return max(3, min(15, int(duration)))


def _run(cmd: list[str], *, timeout: int) -> subprocess.CompletedProcess:
    """Run bl, retry up to 2 times on transient network errors, raise on others."""
    max_attempts = 3
    last_err: RuntimeError | None = None
    for attempt in range(max_attempts):
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(_REPO_ROOT),
        )
        if proc.returncode == 0:
            return proc
        err = RuntimeError(
            f"bl exited {proc.returncode}\nCMD: {' '.join(cmd)}\n"
            f"STDERR:\n{proc.stderr[-2000:]}"
        )
        if attempt + 1 < max_attempts and _is_transient(proc.stderr):
            backoff = 2 ** attempt  # 1s, 2s
            print(
                f"bl transient error (attempt {attempt + 1}/{max_attempts}), "
                f"retrying in {backoff}s",
                file=sys.stderr,
            )
            time.sleep(backoff)
            last_err = err
            continue
        raise err
    assert last_err is not None  # unreachable: loop either returns or raises
    raise last_err


def _json_stdout(proc: subprocess.CompletedProcess) -> dict:
    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"bl returned non-JSON stdout\nCMD: {' '.join(proc.args)}\n"
            f"STDOUT:\n{proc.stdout[-2000:]}\nSTDERR:\n{proc.stderr[-2000:]}"
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"bl returned unexpected JSON: {data!r}")
    return data


def _wait_and_download(task_id: str, out_path: Path, *, timeout_s: int) -> None:
    deadline = time.time() + timeout_s
    poll_s = int(os.environ.get("SPARK_VIDEO_RENDER_POLL_S", "15"))

    while True:
        if time.time() > deadline:
            raise RuntimeError(f"video task {task_id} timed out after {timeout_s}s")

        proc = _run(
            [*_bl_cmd(), "--output", "json", "video", "task", "get",
             "--task-id", task_id],
            timeout=60,
        )
        data = _json_stdout(proc)
        status = str(data.get("task_status") or data.get("status") or "").upper()
        if status in {"SUCCEEDED", "SUCCESS", "FINISHED", "COMPLETED"}:
            break
        if status in {"FAILED", "FAILURE", "CANCELED", "CANCELLED"}:
            raise RuntimeError(f"video task {task_id} failed: {json.dumps(data, ensure_ascii=False)}")
        time.sleep(max(3, poll_s))

    _run(
        [*_bl_cmd(), "--output", "json", "video", "download",
         "--task-id", task_id, "--out", str(out_path)],
        timeout=300,
    )


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

    # HappyHorse's supported floor is 3s. Keep provider-specific limits here;
    # the storyboard remains provider-agnostic.
    duration = _clamp_duration(duration)

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

    # Common flags (skip Nones — argparse defaults pass them through).
    # Use async submission plus explicit task polling/download. In some
    # environments the CLI's long synchronous wait can lose the network socket
    # after a task was successfully submitted.
    cmd += ["--no-wait"]
    # happyhorse-1.0-t2v rejects `parameters.resolution`. Skip it for t2v —
    # the model picks a default. Keep --resolution for i2v/r2v which do accept it.
    if extra.get("resolution") and kind != "t2v":
        cmd += ["--resolution", str(extra["resolution"])]
    if extra.get("ratio"):
        cmd += ["--ratio", str(extra["ratio"])]
    if extra.get("seed") is not None:
        cmd += ["--seed", str(extra["seed"])]
    if extra.get("model"):
        cmd += ["--model", str(extra["model"])]

    # JSON output for parseability
    cmd = [cmd[0]] + ["--output", "json"] + cmd[1:]

    started = time.time()
    timeout_s = int(os.environ.get("SPARK_VIDEO_RENDER_TIMEOUT_S", "900"))
    proc = _run(cmd, timeout=120)
    data = _json_stdout(proc)
    task_id = data.get("task_id")
    if not task_id:
        raise RuntimeError(
            f"bl async submit returned no task_id\nSTDOUT:\n{proc.stdout[-2000:]}"
        )

    _wait_and_download(str(task_id), out_path, timeout_s=timeout_s)
    elapsed = time.time() - started

    if not out_path.exists():
        raise RuntimeError(
            f"bl returned exit 0 but no video at {out_path}\nSTDOUT:\n{proc.stdout[-2000:]}"
        )

    model = extra.get("model") or _infer_default_model(kind)

    return {
        "video_path": str(out_path),
        "model": model,
        "elapsed_s": round(elapsed, 2),
        "task_id": str(task_id),
    }


def _infer_default_model(kind: str) -> str:
    return {
        "t2v": "happyhorse-1.0-t2v",
        "i2v": "happyhorse-1.0-i2v",
        "r2v": "happyhorse-1.0-r2v",
    }.get(kind, "happyhorse-1.0-r2v")
