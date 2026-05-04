"""ffmpeg helpers for frame extraction, concat, downloads."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import httpx
from rich.console import Console

console = Console()


def _ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found in PATH. Install via `brew install ffmpeg`.")


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=300.0, follow_redirects=True) as c, dest.open("wb") as f:
        with c.stream("GET", url) as r:
            r.raise_for_status()
            for chunk in r.iter_bytes(chunk_size=1 << 20):
                f.write(chunk)
    return dest


def extract_last_frame(video: Path, out: Path) -> Path:
    """Extract the very last frame as PNG. Used as next clip's first_frame."""
    _ensure_ffmpeg()
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-sseof", "-0.1", "-i", str(video),
        "-vframes", "1", "-q:v", "2", str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def extract_first_frame(video: Path, out: Path) -> Path:
    _ensure_ffmpeg()
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(video),
        "-vframes", "1", "-q:v", "2", str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def concat(clips: list[Path], out: Path, *, crossfade_s: float = 0.0) -> Path:
    """Concatenate clips. If crossfade_s > 0, applies xfade between each pair.

    For MVP we use the simple concat demuxer (no crossfade, no re-encode).
    Crossfade path falls back to filter_complex re-encode.
    """
    _ensure_ffmpeg()
    out.parent.mkdir(parents=True, exist_ok=True)
    if not clips:
        raise ValueError("no clips to concat")

    if crossfade_s <= 0:
        listfile = out.with_suffix(".txt")
        listfile.write_text("\n".join(f"file '{c.resolve()}'" for c in clips), encoding="utf-8")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(listfile), "-c", "copy", str(out),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return out

    # crossfade path — re-encodes
    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", str(c)]
    n = len(clips)
    filt_parts = []
    last = "[0:v]"
    last_a = "[0:a]"
    offset = 0.0
    # Naive cumulative xfade. Caller should keep clips short to avoid drift.
    for i in range(1, n):
        offset += 8.0 - crossfade_s  # assumes ~8s clips; tune in caller
        filt_parts.append(
            f"{last}[{i}:v]xfade=transition=fade:duration={crossfade_s}:offset={offset:.2f}[v{i}]"
        )
        filt_parts.append(
            f"{last_a}[{i}:a]acrossfade=d={crossfade_s}[a{i}]"
        )
        last = f"[v{i}]"
        last_a = f"[a{i}]"
    filt = ";".join(filt_parts)
    cmd = [
        "ffmpeg", "-y", *inputs, "-filter_complex", filt,
        "-map", last, "-map", last_a,
        "-c:v", "libx264", "-c:a", "aac", str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out
