# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.31"]
# ///
"""
render_shot.py — render a single shot via the configured provider, then
score it (the deterministic half of Zone 3).

Reads SPARK_VIDEO_PROVIDER (default `bl`) and dispatches to the matching
plugin under scripts/providers/. Also updates projects/<p>/<ep>/shots_state.json.

After a successful render the clip is automatically reviewed (6-axis
``bl omni`` score via lib/review.py) unless --no-review is passed or
VIDEOGEN_REVIEW_MODEL is empty. The render→score→promote loop is one
atomic, unskippable tool call:
    * the 6-axis score is embedded into the attempt + written to
      reviews/<shot>-ver<N>.json;
    * on ACCEPT (avg >= threshold) the version is promoted to winner
      (clips/<shot>.mp4) — no separate --accept-version step needed;
    * on REJECT the winner is left unset for the agent to rewrite + retry.
The agent still owns the *judgment*: how to rewrite a REJECTed prompt and
when to escalate to the director.

Usage:
    uv run scripts/render_shot.py --shot S01-001 --kind r2v \\
        --prompt "..." --duration 12 --media a.png b.png \\
        [--voice cast.mp3] [--provider bl|wan27|seedance2] [--force] [--reset-attempts] \\
        [--characters 陆辰 钱夫人] [--no-review] [--skip-animatic-gate]

By default, video rendering is blocked until the static storyboard
reference images have been approved via
`uv run scripts/storyboard.py animatic --confirm`.
If a per-shot storyboard reference image exists for this shot, it is
prepended to --media and the render is sent as r2v reference media, not
as --first-frame.

Re-render flags:
    --force           render again even if a winner exists; keeps prior attempts
    --reset-attempts  wipe attempts and winner, start at version 1 (implies --force)
    (If the winner_path is missing on disk, the stale winner is auto-cleared
     and the next attempt proceeds — no flag needed.)

Stdout (JSON):
    {"shot_id":"S01-001","version":1,"video_path":"...","last_frame_path":"...",
     "duration_s":12.0,"provider":"bl","model":"happyhorse-1.0-r2v","elapsed_s":47.2,
     "review":{"score":8.2,"verdict":"ACCEPT","breakdown":{...},"critique":"..."},
     "winner_version":1}

Exit codes:
    0 = ok (render succeeded; check stdout "review.verdict" for ACCEPT/REJECT/ERROR)
    1 = provider error
    2 = invalid args
    3 = timeout
"""
from __future__ import annotations

import argparse
import fcntl
import importlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from lib.env import load_pwd_dotenv  # noqa: E402
from lib import review as review_mod  # noqa: E402

load_pwd_dotenv()


def _projects_root() -> Path:
    return Path(os.environ.get("VIDEOGEN_PROJECTS_DIR", "./projects")).resolve()


def _episode_dir() -> Path:
    proj = os.environ.get("SPARK_VIDEO_PROJECT")
    ep = os.environ.get("SPARK_VIDEO_EPISODE")
    if not proj or not ep:
        print("ERROR: SPARK_VIDEO_PROJECT and SPARK_VIDEO_EPISODE must be set",
              file=sys.stderr)
        sys.exit(2)
    ep_id = ep if ep.startswith("episode-") else f"episode-{ep}"
    return _projects_root() / proj / ep_id


def _animatic_confirmed(ep_dir: Path) -> bool:
    if os.environ.get("SPARK_VIDEO_SKIP_ANIMATIC_GATE", "").lower() in {
        "1", "true", "yes", "y", "on",
    }:
        return True
    panels_dir = ep_dir / "storyboard-panels"
    return (panels_dir / "panels.json").exists() and (panels_dir / "CONFIRMED").exists()


def _load_state(state_path: Path) -> dict:
    if state_path.exists():
        return json.loads(state_path.read_text())
    return {}


def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    # Per-PID/uuid tmp name so concurrent writers don't collide on the same
    # .tmp path. The final atomic rename is still the single commit point.
    tmp = state_path.with_suffix(f".tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(state_path)


def _update_state(state_path: Path, mutate: Callable[[dict], None]) -> dict:
    """flock-guarded read-modify-write of state_path.

    Why: render_shot.py runs in parallel across shots, all touching the same
    shots_state.json. Without locking, two processes both load → mutate → save
    and the later writer silently overwrites the earlier writer's appended
    attempt. We hold an exclusive flock on a sibling .lock file across the
    full read→mutate→save so the merge is atomic.
    """
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    with open(lock_path, "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            state = _load_state(state_path)
            mutate(state)
            _save_state(state_path, state)
            return state
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def _refresh_viewer() -> None:
    """Best-effort rebuild of viewer.html after state changes."""
    try:
        subprocess.run(
            ["uv", "run", str(_HERE / "build_viewer.py"), "--no-open"],
            check=False, capture_output=True, timeout=30,
        )
    except Exception:
        pass


def _next_version(state: dict, shot_id: str, *, reset: bool) -> int:
    """Return the next persisted clip version.

    Failed provider calls are audit attempts, not clip versions. Only attempts
    that produced a video artifact get to reserve a ``verN`` number.
    """
    if reset:
        state.pop(shot_id, None)
        return 1
    entry = state.get(shot_id)
    if not entry:
        return 1
    attempts = entry.get("attempts", [])
    versions: list[int] = []
    for attempt in attempts:
        if attempt.get("status") == "FAILED":
            continue
        if not attempt.get("video_path"):
            continue
        version = attempt.get("version")
        if isinstance(version, int):
            versions.append(version)
            continue
        try:
            versions.append(int(version))
        except (TypeError, ValueError):
            pass
    return max(versions, default=0) + 1


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


def _shot_characters(ep_dir: Path, shot_id: str) -> list[str]:
    """Read shot.characters from storyboard.json (raw JSON — no pydantic).

    Used to attach the right cast reference images to the review's cast_match axis
    when the caller didn't pass --characters explicitly. Returns [] if the
    storyboard or shot is absent (review still runs, cast_match just weaker).
    """
    sb_path = ep_dir / "storyboard.json"
    if not sb_path.exists():
        return []
    try:
        sb = json.loads(sb_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    for shot in sb.get("shots", []) or []:
        if shot.get("id") == shot_id:
            chars = shot.get("characters") or []
            return [c for c in chars if isinstance(c, str)]
    return []


def _storyboard_shot(ep_dir: Path, shot_id: str) -> dict:
    sb_path = ep_dir / "storyboard.json"
    if not sb_path.exists():
        return {}
    try:
        sb = json.loads(sb_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    for shot in sb.get("shots", []) or []:
        if isinstance(shot, dict) and shot.get("id") == shot_id:
            return shot
    return {}


def _read_lore_style(ep_dir: Path) -> dict[str, str]:
    def parse(lore: Path) -> dict[str, str]:
        if not lore.exists():
            return {}
        text = lore.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return {}
        out: dict[str, str] = {}
        for line in text.splitlines()[1:]:
            if line.strip() == "---":
                break
            if ":" not in line or line.startswith((" ", "\t")):
                continue
            key, raw = line.split(":", 1)
            key = key.strip()
            if key not in {"visual_style", "camera_language", "mood_anchor"}:
                continue
            val = raw.strip().strip("'\"")
            if val:
                out[key] = val
        return out

    out = parse(ep_dir.parent / "lore.md")
    out.update(parse(ep_dir / "lore.md"))
    return out


def _format_mmss(seconds: int) -> str:
    m, s = divmod(max(0, int(seconds)), 60)
    return f"{m:02d}:{s:02d}"


def _structured_video_prompt(
    *,
    ep_dir: Path,
    shot_id: str,
    prompt: str,
    duration: int,
    media: list[str | Path],
    first_frame: str | Path | None,
    voice: str | Path | None,
    characters: list[str],
    reference_image_map: str | None = None,
    reference_audio_map: str | None = None,
) -> str:
    if prompt.lstrip().lower().startswith("style -"):
        return _insert_reference_maps(
            prompt,
            reference_image_map=reference_image_map,
            reference_audio_map=reference_audio_map,
        )

    style = _read_lore_style(ep_dir)
    style_line = (
        os.environ.get("SPARK_VIDEO_PROMPT_STYLE")
        or style.get("mood_anchor")
        or style.get("visual_style")
        or "Cinematic live-action short film, consistent visual style across every clip."
    )
    camera = style.get("camera_language")
    if camera and camera not in style_line:
        style_line = f"{style_line}; {camera}"

    shot = _storyboard_shot(ep_dir, shot_id)
    char_names = characters or [
        c for c in shot.get("characters", []) if isinstance(c, str)
    ]
    char_line = ", ".join(char_names) if char_names else "none"
    if first_frame:
        first_frame_note = "Use the provided first-frame input as the literal continuity bridge."
    elif media:
        first_frame_note = (
            "DO NOT use uploaded reference images as the literal first frame; "
            "treat them as approved storyboard/composition references when "
            "provided, plus identity, location, and prop references."
        )
    else:
        first_frame_note = "No uploaded reference image."

    audio_line = (
        "NO MUSIC. Sound effects, ambient audio, breath sounds, and spoken lines are welcome when specified."
    )
    if voice or reference_audio_map:
        audio_line += (
            " Match each provided reference voice to its corresponding "
            "speaking character."
        )

    sections = [
        f"Style - {style_line}",
        f"First frame note - {first_frame_note}",
    ]
    if reference_image_map:
        sections.append(reference_image_map)
    if reference_audio_map:
        sections.append(reference_audio_map)
    sections.extend([
        f"Characters - {char_line}; describe by natural appearance only, no @tags or social handles.",
        "Age and height - keep ages and relative heights explicit and consistent when the shot includes people.",
        "Voices - yes when dialog, narration, breath, or vocal reactions are specified; keep voice continuity.",
        f"Panel timing - [0:00-{_format_mmss(duration)}]",
        f"Audio - {audio_line}",
        "",
        "Shot content -",
        prompt.rstrip(),
    ])
    return "\n".join(sections).rstrip()


def _load_provider(name: str):
    """Import scripts.providers.<name> dynamically."""
    try:
        mod = importlib.import_module(f"scripts.providers.{name}")
    except ImportError as e:
        raise SystemExit(
            f"unknown provider '{name}'. Available: bl, wan27, seedance2"
        ) from e
    if not hasattr(mod, "render"):
        raise SystemExit(f"provider '{name}' missing render() entrypoint")
    return mod


_REMOTE_MEDIA_PREFIXES = ("http://", "https://", "asset://", "data:")
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}

REFERENCE_IMAGE_MAP_HEADER = "Reference image map:"
REFERENCE_IMAGE_MAP_RULE = (
    "The image numbers must exactly match the actual uploaded reference "
    "image order. Use each image only for its assigned role. Unless an image "
    "is explicitly labeled as a first-frame input, do not treat any reference "
    "image as the video's first frame."
)
REFERENCE_AUDIO_MAP_HEADER = "Reference audio map:"
REFERENCE_AUDIO_MAP_RULE = (
    "Use reference audio only for character voice timbre and speaking style. "
    "Do not treat any reference audio as background music, soundtrack, or a "
    "line that must be repeated verbatim."
)


def _is_remote_media_ref(value: str) -> bool:
    return value.startswith(_REMOTE_MEDIA_PREFIXES)


def _normalise_media_ref(value: str) -> str | Path:
    if _is_remote_media_ref(value):
        return value
    return Path(value).expanduser().resolve()


def _storyboard_reference_for_shot(ep_dir: Path, shot_id: str) -> str | None:
    """Return the approved per-shot storyboard reference image, if present."""
    manifest_path = ep_dir / "storyboard-panels" / "panels.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    for item in manifest.get("panels", []) or []:
        shots = item.get("shots") or []
        if shots != [shot_id]:
            continue
        for image in item.get("images", []) or []:
            ref = str(image)
            if _is_remote_media_ref(ref):
                return ref
            path = Path(ref).expanduser()
            candidates = [path]
            if not path.is_absolute():
                candidates.extend([
                    (manifest_path.parent / path).resolve(),
                    (ep_dir / path).resolve(),
                ])
            for candidate in candidates:
                if candidate.exists():
                    return str(candidate)
    return None


def _ref_key(value: str | Path) -> str:
    if isinstance(value, Path):
        try:
            return str(value.expanduser().resolve())
        except OSError:
            return str(value)
    if _is_remote_media_ref(value):
        return value
    try:
        return str(Path(value).expanduser().resolve())
    except OSError:
        return value


def _looks_like_image_ref(value: str | Path) -> bool:
    if isinstance(value, str) and value.startswith("data:image/"):
        return True
    suffix = _ref_suffix(value)
    if suffix in _AUDIO_EXTS or suffix in _VIDEO_EXTS:
        return False
    return suffix in _IMAGE_EXTS or _is_remote_media_ref(str(value))


def _scan_first_image(folder: Path) -> str | None:
    if not folder.is_dir():
        return None
    for f in sorted(folder.iterdir()):
        if f.is_file() and f.suffix.lower() in _IMAGE_EXTS:
            return str(f)
    return None


def _scan_first_audio(folder: Path) -> str | None:
    if not folder.is_dir():
        return None
    for name in ("voice.mp3", "voice.wav", "voice.m4a"):
        preferred = folder / name
        if preferred.is_file():
            return str(preferred)
    for f in sorted(folder.iterdir()):
        if f.is_file() and f.suffix.lower() in _AUDIO_EXTS:
            return str(f)
    return None


def _asset_records(data, plural_key: str) -> list[dict]:
    if not isinstance(data, dict):
        return []
    if isinstance(data.get(plural_key), list):
        return [x for x in data[plural_key] if isinstance(x, dict)]
    return [x for x in data.values() if isinstance(x, dict)]


def _first_record_image(record: dict) -> str | None:
    for key in ("image_local", "image", "path"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    for value in record.get("images", []) or []:
        if isinstance(value, str) and value:
            return value
    return None


def _record_audio_refs(record: dict) -> list[str]:
    refs: list[str] = []
    for key in ("audio_local", "audio_url", "audio", "voice", "voice_local"):
        value = record.get(key)
        if isinstance(value, str) and value:
            refs.append(value)
    for key in ("voices", "audios", "audios_local"):
        for value in record.get(key, []) or []:
            if isinstance(value, str) and value:
                refs.append(value)
    return refs


def _build_asset_index(
    ep_dir: Path,
    *,
    json_name: str,
    plural_key: str,
    folder_name: str,
) -> dict[str, str]:
    proj_dir = ep_dir.parent
    idx: dict[str, str] = {}
    for data_path in [ep_dir / json_name, proj_dir / json_name]:
        data = _load_json(data_path)
        for record in _asset_records(data, plural_key):
            name = record.get("name")
            image = _first_record_image(record)
            if isinstance(name, str) and image and name not in idx:
                ref = _normalise_media_ref(image)
                if isinstance(ref, str) or ref.exists():
                    idx[name] = str(ref)
    for folder in [ep_dir / folder_name, proj_dir / folder_name]:
        if not folder.is_dir():
            continue
        for asset_dir in sorted(folder.iterdir()):
            if not asset_dir.is_dir() or asset_dir.name in idx:
                continue
            image = _scan_first_image(asset_dir)
            if image:
                idx[asset_dir.name] = str(Path(image).expanduser().resolve())
    return idx


def _build_audio_index(ep_dir: Path) -> dict[str, list[str]]:
    proj_dir = ep_dir.parent
    idx: dict[str, list[str]] = {}
    for data_path in [ep_dir / "cast.json", proj_dir / "cast.json"]:
        data = _load_json(data_path)
        for record in _asset_records(data, "characters"):
            name = record.get("name")
            if not isinstance(name, str) or name in idx:
                continue
            refs: list[str] = []
            for raw in _record_audio_refs(record):
                ref = _normalise_media_ref(raw)
                if isinstance(ref, str) or ref.exists():
                    refs.append(str(ref))
            if refs:
                idx[name] = refs
    for folder in [ep_dir / "cast", ep_dir.parent / "cast"]:
        if not folder.is_dir():
            continue
        for asset_dir in sorted(folder.iterdir()):
            if not asset_dir.is_dir() or asset_dir.name in idx:
                continue
            audio = _scan_first_audio(asset_dir)
            if audio:
                idx[asset_dir.name] = [str(Path(audio).expanduser().resolve())]
    return idx


def _storyboard_scene_set_id(ep_dir: Path, scene_id: str | None) -> str | None:
    if not scene_id:
        return None
    sb = _load_json(ep_dir / "storyboard.json") or {}
    for scene in sb.get("scenes", []) or []:
        if isinstance(scene, dict) and scene.get("id") == scene_id:
            set_id = scene.get("set_id")
            return set_id if isinstance(set_id, str) else None
    return None


def _reference_labels_for_shot(ep_dir: Path, shot_id: str) -> dict[str, str]:
    shot = _storyboard_shot(ep_dir, shot_id)
    labels: dict[str, str] = {}

    storyboard_ref = _storyboard_reference_for_shot(ep_dir, shot_id)
    if storyboard_ref:
        labels[_ref_key(_normalise_media_ref(storyboard_ref))] = (
            "Approved static storyboard reference for this clip. Use it only "
            "for composition, camera angle, character placement, framing, "
            "lighting, key action, and mood. Do not treat it as the first frame."
        )

    cast_index = _build_asset_index(
        ep_dir, json_name="cast.json", plural_key="characters", folder_name="cast"
    )
    for name in shot.get("characters", []) or []:
        if not isinstance(name, str):
            continue
        image = cast_index.get(name)
        if image:
            labels[_ref_key(image)] = (
                f"Character reference for {name}. Preserve the face shape, "
                "hairstyle, costume, body type, apparent age, and identity "
                "continuity from this image, while adapting the rendering to "
                "the shot's declared visual style. Do not copy photorealistic "
                "skin texture or live-action camera realism from the reference."
            )

    set_index = _build_asset_index(
        ep_dir, json_name="movie_set.json", plural_key="sets", folder_name="movie-set"
    )
    set_id = shot.get("set_id") or _storyboard_scene_set_id(ep_dir, shot.get("scene"))
    if isinstance(set_id, str):
        image = set_index.get(set_id)
        if image:
            labels[_ref_key(image)] = (
                f"Location reference for {set_id}. Preserve the architecture, "
                "spatial layout, period details, lighting mood, and main "
                "environmental elements while adapting the rendering to the "
                "shot's declared visual style. Do not override the storyboard "
                "action or character placement."
            )

    prop_index = _build_asset_index(
        ep_dir, json_name="props.json", plural_key="props", folder_name="props"
    )
    for name in shot.get("props", []) or []:
        if not isinstance(name, str):
            continue
        image = prop_index.get(name)
        if image:
            labels[_ref_key(image)] = (
                f"Prop reference for {name}. Preserve the shape, material, "
                "color, texture, and scale from this image while adapting the "
                "rendering to the shot's declared visual style. Do not let the "
                "prop reference override the storyboard action."
            )

    return labels


def _reference_audio_labels_for_shot(ep_dir: Path, shot_id: str) -> dict[str, str]:
    shot = _storyboard_shot(ep_dir, shot_id)
    labels: dict[str, str] = {}
    audio_index = _build_audio_index(ep_dir)
    for name in shot.get("characters", []) or []:
        if not isinstance(name, str):
            continue
        for ref in audio_index.get(name, []) or []:
            labels[_ref_key(ref)] = (
                f"Reference voice for {name}. Use this audio only for that "
                "character's voice timbre, age, emotional color, and speaking "
                "rhythm. Do not copy its words unless the shot prompt says so."
            )
        voice_ref_dir = ep_dir / "voice-refs" / shot_id
        if voice_ref_dir.is_dir():
            for ref in voice_ref_dir.glob(f"{name}.*"):
                if ref.is_file() and ref.suffix.lower() in _AUDIO_EXTS:
                    labels[_ref_key(ref)] = (
                        f"Reference voice for {name}. Use this trimmed audio "
                        "only for that character's voice timbre, age, emotional "
                        "color, and speaking rhythm. Do not copy its words "
                        "unless the shot prompt says so."
                    )
    return labels


def _build_reference_image_map(
    *,
    ep_dir: Path,
    shot_id: str,
    media: list[str | Path],
) -> str | None:
    image_refs = [ref for ref in media if _looks_like_image_ref(ref)]
    if not image_refs:
        return None

    labels = _reference_labels_for_shot(ep_dir, shot_id)
    lines = [REFERENCE_IMAGE_MAP_HEADER]
    for idx, ref in enumerate(image_refs, 1):
        label = labels.get(_ref_key(ref))
        if not label:
            label = (
                "Additional reference image. Use it only for visual consistency "
                "relevant to this clip; do not override the storyboard action, "
                "character identity, location, or prop definitions."
            )
        lines.append(f"Image {idx}: {label}")
    lines.append(REFERENCE_IMAGE_MAP_RULE)
    return "\n".join(lines)


def _build_reference_audio_map(
    *,
    ep_dir: Path,
    shot_id: str,
    media: list[str | Path],
    voice: str | Path | None,
) -> str | None:
    audio_refs = [ref for ref in media if _looks_like_audio_ref(ref)]
    if voice:
        audio_refs.append(voice)
    if not audio_refs:
        return None

    labels = _reference_audio_labels_for_shot(ep_dir, shot_id)
    lines = [REFERENCE_AUDIO_MAP_HEADER]
    for idx, ref in enumerate(audio_refs, 1):
        label = labels.get(_ref_key(ref))
        if not label:
            label = (
                "Additional reference voice. Use it only for voice timbre "
                "consistency relevant to this clip; do not add music."
            )
        lines.append(f"Audio {idx}: {label}")
    lines.append(REFERENCE_AUDIO_MAP_RULE)
    return "\n".join(lines)


def _insert_reference_image_map(prompt: str,
                                reference_image_map: str | None) -> str:
    prompt = prompt.rstrip()
    if not reference_image_map or REFERENCE_IMAGE_MAP_HEADER in prompt:
        return prompt
    return f"{reference_image_map}\n\n{prompt}".rstrip()


def _insert_reference_audio_map(prompt: str,
                                reference_audio_map: str | None) -> str:
    prompt = prompt.rstrip()
    if not reference_audio_map or REFERENCE_AUDIO_MAP_HEADER in prompt:
        return prompt
    return f"{reference_audio_map}\n\n{prompt}".rstrip()


def _insert_reference_maps(prompt: str,
                           *,
                           reference_image_map: str | None,
                           reference_audio_map: str | None) -> str:
    prompt = _insert_reference_image_map(prompt, reference_image_map)
    return _insert_reference_audio_map(prompt, reference_audio_map)


def _with_storyboard_reference_note(prompt: str) -> str:
    marker = "Storyboard reference -"
    if marker in prompt:
        return prompt
    note = (
        "Storyboard reference - The first reference image is the approved "
        "static storyboard reference for this clip. Follow its composition, "
        "camera angle, character placement, framing, lighting, key action, "
        "and mood. Use it as a storyboard/composition reference only; do not "
        "treat it as a literal first frame. Do not copy labels, borders, "
        "captions, or UI from the reference image."
    )
    return f"{note}\n\n{prompt.rstrip()}".rstrip()


def _ref_suffix(value: str | Path) -> str:
    if isinstance(value, Path):
        return value.suffix.lower()
    if value.startswith(("http://", "https://")):
        return Path(urlparse(value).path).suffix.lower()
    if value.startswith("data:audio/"):
        return ".mp3"
    return Path(value).suffix.lower()


def _looks_like_audio_ref(value: str | Path) -> bool:
    return _ref_suffix(value) in _AUDIO_EXTS


def _normalise_provider_name(name: str) -> str:
    value = (name or "bl").strip().lower()
    return {
        "happyhorse": "bl",
        "wan": "dashscope_wan27",
        "wan27": "dashscope_wan27",
        "dashscope_wan27": "dashscope_wan27",
        "seedance": "seedance2",
    }.get(value, value)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shot", required=True, help="shot id, e.g. S01-001")
    ap.add_argument("--kind", required=True, choices=["t2v", "i2v", "r2v"])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--duration", type=int, default=5)
    ap.add_argument("--media", nargs="*", default=[],
                    help="reference media paths; seedance2 also accepts "
                         "http(s)://, asset://, and data: refs")
    ap.add_argument("--voice", default=None,
                    help="reference voice mp3 path; seedance2 also accepts "
                         "http(s)://, asset://, and data: refs")
    ap.add_argument("--first-frame", default=None,
                    help="prev shot's last frame (chain bridging, provider-specific)")
    ap.add_argument("--provider", default=None,
                    help="override SPARK_VIDEO_PROVIDER")
    ap.add_argument("--resolution", default="1080P")
    ap.add_argument("--ratio", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--negative-prompt", default=None,
                    help="providers with negative prompt support; ignored by bl")
    ap.add_argument("--accept-version", type=int, default=None,
                    help="don't render; just mark this version as winner")
    ap.add_argument("--force", action="store_true",
                    help="render even if a winner already exists")
    ap.add_argument("--reset-attempts", action="store_true",
                    help="wipe existing attempts (and winner) before "
                         "rendering — implies --force")
    ap.add_argument("--characters", nargs="*", default=None,
                    help="cast names for the review's cast_match axis; "
                         "defaults to storyboard.json's shot.characters")
    ap.add_argument("--no-review", action="store_true",
                    help="skip the automatic post-render clip review "
                         "(score + ACCEPT/REJECT). Also disabled globally "
                         "when VIDEOGEN_REVIEW_MODEL is set to empty string.")
    ap.add_argument("--skip-animatic-gate", action="store_true",
                    help="allow video rendering before static storyboard "
                         "reference images are confirmed (also "
                         "SPARK_VIDEO_SKIP_ANIMATIC_GATE=1)")
    ap.add_argument("--raw-prompt", action="store_true",
                    help="send --prompt exactly as provided, without the "
                         "standard video prompt structure")
    args = ap.parse_args()

    ep_dir = _episode_dir()
    state_path = ep_dir / "shots_state.json"
    state = _load_state(state_path)

    # --accept-version: promote and exit
    if args.accept_version is not None:
        if args.shot not in state:
            print(f"ERROR: shot {args.shot} has no attempts to accept",
                  file=sys.stderr)
            return 2
        ver = args.accept_version
        src = ep_dir / "clips" / f"{args.shot}-ver{ver}.mp4"
        dst = ep_dir / "clips" / f"{args.shot}.mp4"
        if not src.exists():
            print(f"ERROR: {src} not found", file=sys.stderr)
            return 2
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        import shutil as _sh
        _sh.copy2(src, dst)

        def _promote(s: dict) -> None:
            entry = s.get(args.shot)
            if not entry:
                raise RuntimeError(f"shot {args.shot} disappeared from state")
            entry["winner_version"] = ver
            entry["winner_path"] = str(dst)
            entry["needs_director_rewrite"] = False

        _update_state(state_path, _promote)
        _refresh_viewer()
        print(json.dumps({"shot_id": args.shot, "winner_version": ver,
                          "winner_path": str(dst)}))
        return 0

    if not args.skip_animatic_gate and not _animatic_confirmed(ep_dir):
        print(
            "ERROR: static storyboard reference images are not confirmed. Run "
            "`uv run scripts/storyboard.py animatic --generate`, review "
            f"{ep_dir / 'storyboard-panels'}, then run "
            "`uv run scripts/storyboard.py animatic --confirm`. "
            "Pass --skip-animatic-gate only when you intentionally want to "
            "spend video credits without that approval.",
            file=sys.stderr,
        )
        return 2

    # Skip if winner exists, its file is still on disk, and not forced.
    # If the recorded winner_path is gone (user deleted the clip to retry),
    # fall through and re-render rather than misleading them with "skipped".
    # ``--reset-attempts`` implies the user wants to start over, so it also
    # bypasses the skip-check (otherwise the flag was a no-op without
    # ``--force`` — confusing).
    if (args.shot in state and state[args.shot].get("winner_version")
            and not args.force and not args.reset_attempts):
        existing = state[args.shot]
        winner_path = existing.get("winner_path")
        if winner_path and Path(winner_path).exists():
            print(json.dumps({
                "shot_id": args.shot,
                "version": existing["winner_version"],
                "video_path": winner_path,
                "skipped": "already has winner; pass --force to re-render",
            }))
            return 0
        # Stale winner — clear it so this run isn't blocked.
        print(f"warn: shot {args.shot} winner_path missing on disk "
              f"({winner_path}); clearing winner and re-rendering",
              file=sys.stderr)

        def _clear_stale_winner(s: dict) -> None:
            entry = s.get(args.shot)
            if entry:
                entry["winner_version"] = None
                entry["winner_path"] = None

        _update_state(state_path, _clear_stale_winner)
        state = _load_state(state_path)

    version = _next_version(state, args.shot, reset=args.reset_attempts)
    os.environ["SPARK_VIDEO_SHOT"] = args.shot
    os.environ["SPARK_VIDEO_ATTEMPT"] = str(version)
    os.environ.setdefault("SPARK_VIDEO_PHASE", "render")

    provider_name = _normalise_provider_name(
        args.provider or os.environ.get("SPARK_VIDEO_PROVIDER", "bl")
    )
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
    first_frame = _normalise_media_ref(args.first_frame) if args.first_frame else None
    if first_frame:
        extra["first_frame_url"] = (
            first_frame if provider_name == "seedance2" else str(first_frame)
        )

    # Resolve to absolute paths up front. Providers upload local files by
    # path, and a relative path resolved against a surprising cwd (e.g. when
    # the caller cd'd between collecting paths and invoking us) fails with
    # an opaque "Failed to download …" from the model API.
    media = [_normalise_media_ref(m) for m in args.media]
    voice = _normalise_media_ref(args.voice) if args.voice else None
    storyboard_ref_used = False
    storyboard_ref = _storyboard_reference_for_shot(ep_dir, args.shot)
    if storyboard_ref:
        storyboard_media = _normalise_media_ref(storyboard_ref)
        media = [m for m in media if str(m) != str(storyboard_media)]
        media.insert(0, storyboard_media)
        storyboard_ref_used = True
        if args.kind != "r2v":
            print(
                f"warn: {args.shot} has an approved storyboard reference; "
                f"rendering as r2v instead of {args.kind}",
                file=sys.stderr,
            )
            args.kind = "r2v"
        if first_frame:
            print(
                f"warn: {args.shot} has an approved storyboard reference; "
                "ignoring --first-frame so the storyboard image remains "
                "reference media, not a literal first frame",
                file=sys.stderr,
            )
            first_frame = None
            extra.pop("first_frame_url", None)

    remote_refs = [
        ref for ref in [*media, voice, first_frame]
        if isinstance(ref, str) and ref is not None
    ]
    if remote_refs and provider_name != "seedance2":
        print(
            "ERROR: remote media references are currently only supported "
            f"by --provider seedance2: {remote_refs[0]}",
            file=sys.stderr,
        )
        return 2

    for m in media:
        if isinstance(m, Path) and not m.exists():
            print(f"ERROR: --media file not found: {m}", file=sys.stderr)
            return 2
    if isinstance(voice, Path) and not voice.exists():
        print(f"ERROR: --voice file not found: {voice}", file=sys.stderr)
        return 2
    if isinstance(first_frame, Path) and not first_frame.exists():
        print(f"ERROR: --first-frame file not found: {first_frame}", file=sys.stderr)
        return 2

    # Suppress model-generated BGM — cross-clip music can't be coherent.
    reference_image_map = _build_reference_image_map(
        ep_dir=ep_dir,
        shot_id=args.shot,
        media=media,
    )
    reference_audio_map = _build_reference_audio_map(
        ep_dir=ep_dir,
        shot_id=args.shot,
        media=media,
        voice=voice,
    )
    render_prompt = args.prompt.rstrip()
    if storyboard_ref_used:
        render_prompt = _with_storyboard_reference_note(render_prompt)
    if args.raw_prompt:
        render_prompt = _insert_reference_maps(
            render_prompt,
            reference_image_map=reference_image_map,
            reference_audio_map=reference_audio_map,
        )
    else:
        render_prompt = _structured_video_prompt(
            ep_dir=ep_dir,
            shot_id=args.shot,
            prompt=render_prompt,
            duration=args.duration,
            media=media,
            first_frame=first_frame,
            voice=voice,
            characters=args.characters or [],
            reference_image_map=reference_image_map,
            reference_audio_map=reference_audio_map,
        )
    has_seedance_reference_audio = (
        provider_name == "seedance2"
        and any(_looks_like_audio_ref(ref) for ref in media)
    )
    if (
        "no background music" not in render_prompt.lower()
        and not has_seedance_reference_audio
    ):
        render_prompt += " No background music."

    started = datetime.now(timezone.utc).isoformat()
    try:
        result = mod.render(
            kind=args.kind,
            prompt=render_prompt,
            media=media,
            voice=voice,
            duration=args.duration,
            out_path=clip_path,
            extra=extra,
        )
    except Exception as e:
        # Record the failed attempt (locked merge — see _update_state docstring).
        # It does not get a formal clip version because no video artifact was
        # produced; target_version documents the filename we intended to use.
        attempt = {
            "target_version": version,
            "status": "FAILED",
            "started_at": started,
            "error": str(e),
            "provider": provider_name,
            "prompt": args.prompt,
        }

        def _append_failed(s: dict) -> None:
            entry = s.setdefault(args.shot, {
                "shot_id": args.shot, "attempts": [], "winner_version": None,
                "winner_path": None, "needs_director_rewrite": False,
            })
            entry["attempts"].append(attempt)

        _update_state(state_path, _append_failed)
        print(f"ERROR: {e}", file=sys.stderr)
        if isinstance(e, TimeoutError):
            return 3
        return 1

    # Extract last frame for chain bridging
    extracted = _extract_last_frame(clip_path, frame_path)
    last_frame = str(frame_path) if extracted else None

    # Record attempt (locked merge — see _update_state docstring)
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

    def _append_succeeded(s: dict) -> None:
        entry = s.setdefault(args.shot, {
            "shot_id": args.shot, "attempts": [], "winner_version": None,
            "winner_path": None, "needs_director_rewrite": False,
        })
        entry["attempts"].append(attempt)

    _update_state(state_path, _append_succeeded)

    # ── Automatic clip review (Zone 3, formerly the agent's manual step) ──
    # Render → score → (auto-promote on ACCEPT) is now one atomic tool call so
    # an inferior agent can't silently skip scoring. The agent keeps the
    # judgment: rewriting a REJECTed prompt and deciding to escalate.
    review = None
    auto_promoted = False
    if not args.no_review:
        characters = (args.characters if args.characters is not None
                      else _shot_characters(ep_dir, args.shot))
        try:
            review = review_mod.score_clip(
                ep_dir=ep_dir,
                shot_id=args.shot,
                version=version,
                video_path=clip_path,
                characters=characters,
                prompt=args.prompt,
                duration=args.duration,
            )
        except Exception as e:  # never lose a render over a review crash
            print(f"warn: review crashed for {args.shot} v{version}: {e}",
                  file=sys.stderr)
            review = {"score": None, "verdict": "ERROR", "error": str(e)}

    if review is not None:
        accept = review.get("verdict") == "ACCEPT"
        winner_dst = ep_dir / "clips" / f"{args.shot}.mp4"
        if accept:
            if winner_dst.is_symlink() or winner_dst.exists():
                winner_dst.unlink()
            import shutil as _sh
            _sh.copy2(clip_path, winner_dst)

        def _embed_review(s: dict) -> None:
            entry = s.setdefault(args.shot, {
                "shot_id": args.shot, "attempts": [], "winner_version": None,
                "winner_path": None, "needs_director_rewrite": False,
            })
            for a in entry["attempts"]:
                if a.get("version") == version:
                    a["review"] = review
                    break
            if accept:
                entry["winner_version"] = version
                entry["winner_path"] = str(winner_dst)
                entry["needs_director_rewrite"] = False

        _update_state(state_path, _embed_review)
        auto_promoted = accept

    _refresh_viewer()

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
    if review is not None:
        out["review"] = {
            "score": review.get("score"),
            "verdict": review.get("verdict"),
            "breakdown": review.get("breakdown"),
            "critique": review.get("critique"),
        }
        out["winner_version"] = version if auto_promoted else None
        if review.get("verdict") == "REJECT":
            out["next"] = ("rewrite prompt and re-render (--force), or accept "
                           "best-of-N with --accept-version when retries exhausted")
        elif review.get("verdict") == "ERROR":
            out["next"] = ("review could not run; inspect logs/model_calls.jsonl, "
                           "then re-render or accept manually with --accept-version")
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
