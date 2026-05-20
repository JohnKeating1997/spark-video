# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.31"]
# ///
"""
render_shot.py — render a single shot via the configured provider.

Reads SPARK_VIDEO_PROVIDER (default `bl`) and dispatches to the matching
plugin under scripts/providers/. Also updates projects/<p>/<ep>/shots_state.json.

Usage:
    uv run scripts/render_shot.py --shot S01-001 --kind r2v \\
        --prompt "..." --duration 12 --media a.png b.png \\
        [--voice cast.mp3] [--provider bl|wan27] [--force] [--reset-attempts]

Stdout (JSON):
    {"shot_id":"S01-001","version":1,"video_path":"...","last_frame_path":"...",
     "duration_s":12.0,"provider":"bl","model":"happyhorse-1.0-r2v","elapsed_s":47.2}

Exit codes:
    0 = ok
    1 = provider error
    2 = invalid args
    3 = timeout
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))


def _episode_dir() -> Path:
    proj = os.environ.get("SPARK_VIDEO_PROJECT")
    ep = os.environ.get("SPARK_VIDEO_EPISODE")
    if not proj or not ep:
        print("ERROR: SPARK_VIDEO_PROJECT and SPARK_VIDEO_EPISODE must be set",
              file=sys.stderr)
        sys.exit(2)
    ep_id = ep if ep.startswith("episode-") else f"episode-{ep}"
    return Path("projects") / proj / ep_id


def _load_state(state_path: Path) -> dict:
    if state_path.exists():
        return json.loads(state_path.read_text())
    return {}


def _save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(state_path)


def _next_version(state: dict, shot_id: str, *, reset: bool) -> int:
    if reset:
        state.pop(shot_id, None)
        return 1
    entry = state.get(shot_id)
    if not entry:
        return 1
    attempts = entry.get("attempts", [])
    return max((a.get("version", 0) for a in attempts), default=0) + 1


def _extract_last_frame(video_path: Path, frame_path: Path) -> bool:
    """Extract last frame via ffmpeg. Returns True on success.

    Uses -sseof -1 (1s before EOF) + -update 1 because shorter -sseof
    values like -0.05 fail on some encoders ("Output file is empty").
    """
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-sseof", "-1", "-i", str(video_path),
             "-update", "1", "-frames:v", "1", "-q:v", "2", str(frame_path)],
            capture_output=True, timeout=60, check=True,
        )
        return frame_path.exists()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError) as e:
        print(f"warn: extract_last_frame failed: {e}", file=sys.stderr)
        return False


def _load_provider(name: str):
    """Import scripts.providers.<name> dynamically."""
    try:
        mod = importlib.import_module(f"scripts.providers.{name}")
    except ImportError as e:
        raise SystemExit(
            f"unknown provider '{name}'. Available: bl, dashscope_wan27"
        ) from e
    if not hasattr(mod, "render"):
        raise SystemExit(f"provider '{name}' missing render() entrypoint")
    return mod


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shot", required=True, help="shot id, e.g. S01-001")
    ap.add_argument("--kind", required=True, choices=["t2v", "i2v", "r2v"])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--duration", type=int, default=5)
    ap.add_argument("--media", nargs="*", default=[], help="reference image paths")
    ap.add_argument("--voice", default=None, help="reference voice mp3")
    ap.add_argument("--first-frame", default=None,
                    help="prev shot's last frame (chain bridging, wan27 only)")
    ap.add_argument("--provider", default=None,
                    help="override SPARK_VIDEO_PROVIDER")
    ap.add_argument("--resolution", default="1080P")
    ap.add_argument("--ratio", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--negative-prompt", default=None,
                    help="wan27 only; ignored on bl")
    ap.add_argument("--accept-version", type=int, default=None,
                    help="don't render; just mark this version as winner")
    ap.add_argument("--force", action="store_true",
                    help="render even if a winner already exists")
    ap.add_argument("--reset-attempts", action="store_true",
                    help="wipe existing attempts before rendering")
    args = ap.parse_args()

    ep_dir = _episode_dir()
    state_path = ep_dir / "shots_state.json"
    state = _load_state(state_path)

    # --accept-version: promote and exit
    if args.accept_version is not None:
        entry = state.get(args.shot)
        if not entry:
            print(f"ERROR: shot {args.shot} has no attempts to accept",
                  file=sys.stderr)
            return 2
        ver = args.accept_version
        src = ep_dir / "clips" / f"{args.shot}-ver{ver}.mp4"
        dst = ep_dir / "clips" / f"{args.shot}.mp4"
        if not src.exists():
            print(f"ERROR: {src} not found", file=sys.stderr)
            return 2
        import shutil as _sh
        _sh.copy2(src, dst)
        entry["winner_version"] = ver
        entry["winner_path"] = str(dst)
        entry["needs_director_rewrite"] = False
        _save_state(state_path, state)
        print(json.dumps({"shot_id": args.shot, "winner_version": ver,
                          "winner_path": str(dst)}))
        return 0

    # Skip if winner exists and not forced
    if (args.shot in state and state[args.shot].get("winner_version")
            and not args.force):
        existing = state[args.shot]
        print(json.dumps({
            "shot_id": args.shot,
            "version": existing["winner_version"],
            "video_path": existing.get("winner_path"),
            "skipped": "already has winner; pass --force to re-render",
        }))
        return 0

    version = _next_version(state, args.shot, reset=args.reset_attempts)
    os.environ["SPARK_VIDEO_SHOT"] = args.shot
    os.environ["SPARK_VIDEO_ATTEMPT"] = str(version)
    os.environ.setdefault("SPARK_VIDEO_PHASE", "render")

    provider_name = args.provider or os.environ.get("SPARK_VIDEO_PROVIDER", "bl")
    if provider_name == "wan27":
        provider_name = "dashscope_wan27"
    mod = _load_provider(provider_name)

    clip_path = ep_dir / "clips" / f"{args.shot}-ver{version}.mp4"
    frame_path = ep_dir / "frames" / f"{args.shot}-ver{version}_last.png"

    extra = {
        "resolution": args.resolution,
        "ratio": args.ratio,
        "seed": args.seed,
    }
    if args.negative_prompt:
        extra["negative_prompt"] = args.negative_prompt
    if args.first_frame:
        extra["first_frame_url"] = args.first_frame

    media = [Path(m) for m in args.media]
    voice = Path(args.voice) if args.voice else None

    started = datetime.now(timezone.utc).isoformat()
    try:
        result = mod.render(
            kind=args.kind,
            prompt=args.prompt,
            media=media,
            voice=voice,
            duration=args.duration,
            out_path=clip_path,
            extra=extra,
        )
    except Exception as e:
        # Record the failed attempt
        attempt = {
            "version": version,
            "status": "FAILED",
            "started_at": started,
            "error": str(e),
            "provider": provider_name,
            "prompt": args.prompt,
        }
        entry = state.setdefault(args.shot, {
            "shot_id": args.shot, "attempts": [], "winner_version": None,
            "winner_path": None, "needs_director_rewrite": False,
        })
        entry["attempts"].append(attempt)
        _save_state(state_path, state)
        print(f"ERROR: {e}", file=sys.stderr)
        if isinstance(e, TimeoutError):
            return 3
        return 1

    # Extract last frame for chain bridging
    extracted = _extract_last_frame(clip_path, frame_path)
    last_frame = str(frame_path) if extracted else None

    # Record attempt
    attempt = {
        "version": version,
        "status": "SUCCEEDED",
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider_name,
        "model": result.get("model"),
        "video_path": result["video_path"],
        "last_frame_path": last_frame,
        "elapsed_s": result.get("elapsed_s"),
        "prompt": args.prompt,
    }
    entry = state.setdefault(args.shot, {
        "shot_id": args.shot, "attempts": [], "winner_version": None,
        "winner_path": None, "needs_director_rewrite": False,
    })
    entry["attempts"].append(attempt)
    _save_state(state_path, state)

    out = {
        "shot_id": args.shot,
        "version": version,
        "video_path": result["video_path"],
        "last_frame_path": last_frame,
        "duration_s": float(args.duration),
        "provider": provider_name,
        "model": result.get("model"),
        "elapsed_s": result.get("elapsed_s"),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
