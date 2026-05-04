"""Render a single shot into an MP4 using the appropriate Wan model.

Render pipeline per shot:
  1. Build `media[]` based on shot.model + characters + prev last frame.
  2. Submit task to Wan.
  3. Wait until terminal.
  4. Download MP4 + extract last frame.
  5. Update shots_state.json with status + paths.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from rich.console import Console

from . import cast as cast_mod, ffmpeg as ff, state, wan
from .config import SETTINGS
from .storyboard import Shot, Storyboard

console = Console()


def _media_for_shot(shot: Shot, cast_data: dict, prev_last_frame_url: str | None) -> tuple[str, list[dict]]:
    """Return (model, media[]) for the Wan request."""
    char_index = {c["name"]: c for c in cast_data["characters"]}

    media: list[dict] = []

    if shot.model == "wan2.7-r2v":
        # reference_image (+ optional reference_voice) per character
        for name in shot.characters:
            c = char_index.get(name)
            if not c:
                raise ValueError(f"shot {shot.id} references unknown cast '{name}'")
            entry: dict[str, Any] = {"type": "reference_image", "url": c["image_url"]}
            if c.get("audio_url"):
                entry["reference_voice"] = c["audio_url"]
            media.append(entry)
        if prev_last_frame_url and shot.use_prev_last_frame_as_first:
            media.append({"type": "first_frame", "url": prev_last_frame_url})

    elif shot.model == "wan2.7-i2v-2026-04-25":
        if not prev_last_frame_url:
            raise ValueError(f"i2v shot {shot.id} needs a previous last frame; mark first shot as t2v or r2v.")
        media.append({"type": "first_frame", "url": prev_last_frame_url})

    return shot.model, media


def _shot_state_key(shot_id: str) -> str:
    return shot_id


def render_shot(
    project_id: str,
    shot: Shot,
    *,
    prev_last_frame_url: str | None,
    storyboard: Storyboard,
) -> dict:
    cast_data = cast_mod.load(project_id)
    model, media = _media_for_shot(shot, cast_data, prev_last_frame_url)

    input_obj: dict[str, Any] = {"prompt": shot.prompt}
    if shot.negative_prompt:
        input_obj["negative_prompt"] = shot.negative_prompt
    if media:
        input_obj["media"] = media

    parameters: dict[str, Any] = {
        "resolution": storyboard.resolution,
        "ratio": storyboard.ratio,
        "duration": shot.duration,
        "prompt_extend": True,
        "watermark": False,
    }
    if shot.seed is not None:
        parameters["seed"] = shot.seed

    console.print(f"[bold cyan]→ submit {shot.id}[/] model={model} dur={shot.duration}s")
    resp = wan.submit(model, input=input_obj, parameters=parameters)
    task_id = resp["output"]["task_id"]

    state.merge_state(project_id, {f"task:{shot.id}": task_id})

    result = wan.wait(task_id)
    status = result.get("output", {}).get("task_status")
    if status != "SUCCEEDED":
        msg = result.get("output", {}).get("message") or result
        console.print(f"[red]✗ {shot.id} {status}: {msg}[/]")
        return {"shot_id": shot.id, "status": status, "error": msg, "task_id": task_id}

    video_url = result["output"]["video_url"]
    pdir = state.project_dir(project_id)
    clip_path = pdir / "clips" / f"{shot.id}.mp4"
    ff.download(video_url, clip_path)

    last_frame = pdir / "frames" / f"{shot.id}_last.png"
    ff.extract_last_frame(clip_path, last_frame)

    out = {
        "shot_id": shot.id,
        "status": "SUCCEEDED",
        "task_id": task_id,
        "video_url": video_url,
        "clip_path": str(clip_path),
        "last_frame_path": str(last_frame),
    }
    console.print(f"[green]✓ {shot.id} → {clip_path}[/]")
    return out


def render_all(project_id: str, storyboard: Storyboard, *, only_missing: bool = True) -> dict:
    """Render all shots sequentially (last_frame chain demands this).

    `only_missing=True` skips shots whose clip already exists — enables resume.
    """
    pdir = state.project_dir(project_id)
    shots_state = state.read_json(project_id, "shots_state.json", default={}) or {}

    prev_last_frame_url: str | None = None
    for shot in storyboard.shots:
        clip_path = pdir / "clips" / f"{shot.id}.mp4"
        last_frame = pdir / "frames" / f"{shot.id}_last.png"

        if only_missing and clip_path.exists() and last_frame.exists():
            console.print(f"[dim]· skip {shot.id} (cached)[/]")
            shots_state[shot.id] = {
                "status": "SUCCEEDED",
                "clip_path": str(clip_path),
                "last_frame_path": str(last_frame),
            }
            # still need a usable URL for the next iteration — upload the cached frame
            prev_last_frame_url = _ensure_frame_url(shots_state[shot.id])
            continue

        # Upload prev last frame if we have one but no URL yet
        prev_url = prev_last_frame_url
        if prev_url is None and shot.use_prev_last_frame_as_first:
            # First shot of the run; that's fine — fall back to no first_frame.
            pass

        out = render_shot(
            project_id, shot, prev_last_frame_url=prev_url, storyboard=storyboard
        )
        shots_state[shot.id] = out
        state.write_json(project_id, "shots_state.json", shots_state)

        if out["status"] != "SUCCEEDED":
            console.print(f"[red]aborting at {shot.id}[/]")
            break

        # Upload last frame so next iteration can pass it via URL
        prev_last_frame_url = _ensure_frame_url(out)

    return shots_state


def _ensure_frame_url(shot_state: dict) -> str | None:
    """Make sure `shot_state` has an `last_frame_url` (oss://). Upload if needed."""
    if shot_state.get("last_frame_url"):
        return shot_state["last_frame_url"]
    p = shot_state.get("last_frame_path")
    if not p or not Path(p).exists():
        return None
    from . import upload as up
    url = up.upload(p)
    shot_state["last_frame_url"] = url
    return url
