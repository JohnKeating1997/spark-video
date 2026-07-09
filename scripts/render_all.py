# /// script
# requires-python = ">=3.10"
# dependencies = ["pydantic>=2.5"]
# ///
"""
render_all.py — batch-render all (or a subset of) shots in one command.

Reads storyboard.json, resolves media from per-shot storyboard reference
images + cast.json / movie_set.json / props.json, computes chain groups
for parallelism, and invokes render_shot.py per shot with correct
arguments. Chain groups run in parallel; shots within a chain run
sequentially, with first-frame bridging skipped for shots that use an
approved storyboard reference image.

Usage:
    # Full reset — re-render everything from scratch:
    uv run scripts/render_all.py --reset --ratio 9:16

    # Only re-render shots that failed or have no winner:
    uv run scripts/render_all.py --failed-only

    # Only re-render shots whose review verdict was REJECT:
    uv run scripts/render_all.py --rejected-only

    # Re-render specific shots:
    uv run scripts/render_all.py --shot S01-002 --shot S03-004

    # Adjust concurrency:
    uv run scripts/render_all.py --reset --concurrency 8

Stdout: JSON summary {"accepted": N, "rejected": N, "failed": N, "total": N}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from lib.storyboard import Storyboard  # noqa: E402
from lib.render_graph import compute_chain_groups  # noqa: E402

_REMOTE_MEDIA_PREFIXES = ("http://", "https://", "asset://", "data:")


def _is_remote_media_ref(value: str) -> bool:
    return value.startswith(_REMOTE_MEDIA_PREFIXES)


def _normalise_provider_name(name: str | None) -> str:
    value = (name or "bl").strip().lower()
    return {
        "happyhorse": "bl",
        "wan": "dashscope_wan27",
        "wan27": "dashscope_wan27",
        "dashscope_wan27": "dashscope_wan27",
        "seedance": "seedance2",
    }.get(value, value)


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


def _load_json(p: Path):
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _build_animatic_index(ep_dir: Path) -> dict[str, str]:
    """Map shot id -> approved per-shot storyboard reference image."""
    manifest = _load_json(ep_dir / "storyboard-panels" / "panels.json") or {}
    idx: dict[str, str] = {}
    for item in manifest.get("panels", []) or []:
        shots = item.get("shots") or []
        if len(shots) != 1:
            continue
        shot_id = shots[0]
        if not isinstance(shot_id, str) or not shot_id:
            continue
        for image in item.get("images", []) or []:
            ref = str(image)
            if _is_remote_media_ref(ref):
                idx[shot_id] = ref
                break
            path = Path(ref)
            if path.exists():
                idx[shot_id] = str(path)
                break
    return idx


def _with_storyboard_reference_note(prompt: str,
                                    has_animatic_reference: bool) -> str:
    """Tell the video model how to use the per-shot storyboard image."""
    if not has_animatic_reference:
        return prompt
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


def _resolve_media(shot, scenes_by_id: dict, cast_index: dict,
                   set_index: dict, prop_index: dict,
                   animatic_index: dict[str, str] | None = None) -> list[str]:
    """Build --media: storyboard reference image -> cast -> set -> props.

    Keep this order stable: render_shot.py turns the actual uploaded image
    order into Image 1 / Image 2 / ... reference-map text in the final
    provider prompt.
    """
    media = []
    animatic_ref = (animatic_index or {}).get(shot.id)
    has_animatic_ref = False
    if animatic_ref and (_is_remote_media_ref(animatic_ref)
                         or Path(animatic_ref).exists()):
        media.append(animatic_ref)
        has_animatic_ref = True

    if shot.kind == "t2v" and not has_animatic_ref:
        return []

    for char in shot.characters:
        path = cast_index.get(char)
        if path and (_is_remote_media_ref(path) or Path(path).exists()):
            media.append(path)

    effective_set_id = shot.set_id
    if effective_set_id is None:
        scene = scenes_by_id.get(shot.scene)
        if scene:
            effective_set_id = scene.get("set_id")
    if effective_set_id and effective_set_id in set_index:
        path = set_index[effective_set_id]
        if path and (_is_remote_media_ref(path) or Path(path).exists()):
            media.append(path)

    for prop_name in (shot.props or []):
        path = prop_index.get(prop_name)
        if path and (_is_remote_media_ref(path) or Path(path).exists()):
            media.append(path)

    return media


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def _parse_render_stdout(stdout: str) -> dict | None:
    """Extract the render result JSON from render_shot.py stdout.

    render_shot.py prints one JSON line as its result, but uv/pip install
    messages or _refresh_viewer() output may appear before or after it.
    We scan lines in reverse and return the first valid JSON with "shot_id".
    """
    if not stdout or not stdout.strip():
        return None
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and ("shot_id" in obj or "video_path" in obj):
                return obj
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _scan_first_image(folder: Path) -> str | None:
    """Return the first image file in a folder, or None."""
    if not folder.is_dir():
        return None
    for name in ("cast.png", "portrait.png", "set.png", "prop.png"):
        preferred = folder / name
        if preferred.is_file():
            return str(preferred)
    for f in sorted(folder.iterdir()):
        if f.is_file() and f.suffix.lower() in _IMAGE_EXTS:
            return str(f)
    return None


def _scan_first_audio(folder: Path) -> str | None:
    """Return the preferred voice sample in a folder, or None."""
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
    value = data.get(plural_key)
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        return [x for x in value.values() if isinstance(x, dict)]
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


def _normalise_manifest_ref(ref: str) -> str | None:
    if _is_remote_media_ref(ref):
        return ref
    path = Path(ref).expanduser()
    try:
        return str(path.resolve()) if path.exists() else None
    except OSError:
        return None


def _normalise_manifest_image(image: str) -> str | None:
    return _normalise_manifest_ref(image)


def _build_asset_index(
    ep_dir: Path,
    *,
    json_name: str,
    plural_key: str,
    folder_name: str,
) -> dict[str, str]:
    """Map asset name to image path from manifest, with folder fallback."""
    proj_dir = ep_dir.parent
    idx: dict[str, str] = {}
    for data_path in [ep_dir / json_name, proj_dir / json_name]:
        data = _load_json(data_path)
        for record in _asset_records(data, plural_key):
            name = record.get("name")
            image = _first_record_image(record)
            ref = _normalise_manifest_image(image) if isinstance(image, str) else None
            if isinstance(name, str) and ref and name not in idx:
                idx[name] = ref
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


def _build_cast_index(ep_dir: Path) -> dict[str, str]:
    """Map character name → portrait path from cast.json, with folder fallback."""
    return _build_asset_index(
        ep_dir, json_name="cast.json", plural_key="characters", folder_name="cast"
    )


def _build_cast_voice_index(ep_dir: Path) -> dict[str, list[str]]:
    """Map character name -> available voice reference paths."""
    proj_dir = ep_dir.parent
    idx: dict[str, list[str]] = {}
    for data_path in [ep_dir / "cast.json", proj_dir / "cast.json"]:
        data = _load_json(data_path)
        for record in _asset_records(data, "characters"):
            name = record.get("name")
            if not isinstance(name, str) or name in idx:
                continue
            refs = [
                ref for raw in _record_audio_refs(record)
                if (ref := _normalise_manifest_ref(raw))
            ]
            if refs:
                idx[name] = refs
    for folder in [ep_dir / "cast", proj_dir / "cast"]:
        if not folder.is_dir():
            continue
        for asset_dir in sorted(folder.iterdir()):
            if not asset_dir.is_dir() or asset_dir.name in idx:
                continue
            audio = _scan_first_audio(asset_dir)
            if audio:
                idx[asset_dir.name] = [str(Path(audio).expanduser().resolve())]
    return idx


def _shot_speakers(shot) -> list[str]:
    """Infer speaking characters from prompt text.

    Voice references should guide generated dialogue, not silent background
    characters. If the shot has dialogue but we cannot infer speakers, fall
    back to all characters so older storyboards still get a voice cue.
    """
    prompt = getattr(shot, "prompt", "") or ""
    has_dialogue = any(mark in prompt for mark in ("：“", ":\"", "：\"", "“"))
    char_names = list(shot.characters)
    speakers: list[str] = []
    seen: set[str] = set()

    def add(name: str | None) -> None:
        if name and name in char_names and name not in seen:
            speakers.append(name)
            seen.add(name)

    def last_char(text: str) -> str | None:
        positions = [
            (text.rfind(name), name)
            for name in char_names
            if text.rfind(name) >= 0
        ]
        if not positions:
            return None
        return max(positions, key=lambda item: item[0])[1]

    # Explicit script hints like "only X speaks" are more reliable than
    # grammatical inference from long Chinese blocking sentences.
    for name in char_names:
        if re.search(rf"(?:只有|只由){re.escape(name)}(?:一个人)?(?:开口|说话)", prompt):
            add(name)

    for match in re.finditer(r"[：:]\s*[“\"]", prompt):
        prefix = prompt[:match.start()]
        boundary = max(
            prefix.rfind(mark)
            for mark in ("。", "；", ";", "！", "？", "”", "\"", "\n")
        )
        clause = prefix[boundary + 1:]

        # "A ... 向/看着 B ... 说" means A speaks to B; the nearest name
        # before the verb may be B, so handle these constructions first.
        for marker in ("向", "看着", "望着", "对着"):
            idx = clause.rfind(marker)
            if idx > 0:
                speaker = last_char(clause[:idx])
                if speaker:
                    add(speaker)
                    break
        else:
            add(last_char(clause))

    if speakers:
        return speakers
    return list(shot.characters) if has_dialogue else []


def _resolve_voice_media_entries(
    shot,
    cast_voice_index: dict[str, list[str]],
) -> list[tuple[str, str]]:
    """Return de-duplicated (character, voice-ref) pairs in speaking order."""
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for char in _shot_speakers(shot):
        for ref in cast_voice_index.get(char, []) or []:
            if ref in seen:
                continue
            if _is_remote_media_ref(ref) or Path(ref).exists():
                entries.append((char, ref))
                seen.add(ref)
    return entries


def _resolve_voice_media(shot, cast_voice_index: dict[str, list[str]]) -> list[str]:
    """Return de-duplicated voice refs in speaking-character order."""
    return [ref for _, ref in _resolve_voice_media_entries(shot, cast_voice_index)]


def _audio_duration_s(ref: str) -> float | None:
    if _is_remote_media_ref(ref):
        return None
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                ref,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return float(proc.stdout.strip())
    except Exception:
        return None


def _fit_seedance_voice_refs(
    ep_dir: Path,
    shot_id: str,
    entries: list[tuple[str, str]],
    *,
    max_total_s: float = 14.0,
) -> list[str]:
    """Trim local multi-voice references under Seedance's total duration cap."""
    if len(entries) <= 1:
        return [ref for _, ref in entries]

    durations = [_audio_duration_s(ref) for _, ref in entries]
    known_total = sum(d for d in durations if d is not None)
    if known_total <= max_total_s:
        return [ref for _, ref in entries]

    per_ref_s = max_total_s / len(entries)
    out_dir = ep_dir / "voice-refs" / shot_id
    out_dir.mkdir(parents=True, exist_ok=True)
    fitted: list[str] = []
    for (char, ref), duration in zip(entries, durations):
        if _is_remote_media_ref(ref) or duration is None or duration <= per_ref_s:
            fitted.append(ref)
            continue
        out = out_dir / f"{char}.mp3"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", ref,
                "-t", f"{per_ref_s:.3f}",
                "-ac", "1", "-ar", "24000",
                "-c:a", "libmp3lame", "-b:a", "128k",
                str(out),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        fitted.append(str(out))
    return fitted


def _build_set_index(ep_dir: Path) -> dict[str, str]:
    """Map set name → set image path from movie_set.json, with folder fallback."""
    return _build_asset_index(
        ep_dir, json_name="movie_set.json", plural_key="sets", folder_name="movie-set"
    )


def _build_prop_index(ep_dir: Path) -> dict[str, str]:
    """Map prop name → prop image path from props.json, with folder fallback."""
    return _build_asset_index(
        ep_dir, json_name="props.json", plural_key="props", folder_name="props"
    )


def _should_render(shot_id: str, state: dict, *, mode: str) -> bool:
    """Decide whether a shot should be rendered based on filter mode."""
    if mode == "reset":
        return True
    entry = state.get(shot_id)
    if not entry:
        return True
    if mode == "failed-only":
        if entry.get("winner_version"):
            winner_path = entry.get("winner_path")
            if winner_path and Path(winner_path).exists():
                return False
        attempts = entry.get("attempts", [])
        if not attempts:
            return True
        last = attempts[-1]
        if last.get("status") == "FAILED":
            return True
        if not entry.get("winner_version"):
            return True
        return False
    if mode == "rejected-only":
        if entry.get("winner_version"):
            return False
        attempts = entry.get("attempts", [])
        if not attempts:
            return True
        last = attempts[-1]
        review = last.get("review", {})
        if review.get("verdict") == "REJECT":
            return True
        if last.get("status") == "FAILED":
            return True
        return False
    return True


def _render_chain_group(
    group: list[str],
    ep_dir: Path,
    shots_by_id: dict,
    scenes_by_id: dict,
    cast_index: dict,
    cast_voice_index: dict,
    set_index: dict,
    prop_index: dict,
    animatic_index: dict[str, str],
    state: dict,
    *,
    mode: str,
    target_shots: list[str] | None = None,
    ratio: str | None,
    provider: str | None,
    no_review: bool,
    skip_animatic_gate: bool,
) -> list[dict]:
    """Render one chain group sequentially, passing first-frame when safe."""
    results = []
    prev_last_frame: str | None = None

    for shot_id in group:
        if not _should_render(shot_id, state, mode=mode):
            results.append({"shot_id": shot_id, "skipped": True})
            entry = state.get(shot_id, {})
            attempts = entry.get("attempts", [])
            if attempts:
                last_ok = [a for a in attempts if a.get("last_frame_path")]
                if last_ok:
                    prev_last_frame = last_ok[-1]["last_frame_path"]
            continue

        shot = shots_by_id.get(shot_id)
        if not shot:
            results.append({"shot_id": shot_id, "error": "not in storyboard"})
            continue

        animatic_ref = animatic_index.get(shot_id)
        has_animatic_reference = bool(animatic_ref)
        media = _resolve_media(
            shot, scenes_by_id, cast_index, set_index, prop_index, animatic_index
        )
        voice_entries = _resolve_voice_media_entries(shot, cast_voice_index)
        provider_name = _normalise_provider_name(
            provider or os.environ.get("SPARK_VIDEO_PROVIDER", "bl")
        )
        voice_arg: str | None = None
        voice_refs = [ref for _, ref in voice_entries]
        if voice_refs:
            if provider_name == "seedance2":
                voice_refs = _fit_seedance_voice_refs(ep_dir, shot_id, voice_entries)
                media.extend(voice_refs)
            else:
                voice_arg = voice_refs[0]
        render_kind = "r2v" if has_animatic_reference else shot.kind
        render_prompt = _with_storyboard_reference_note(
            shot.prompt, has_animatic_reference
        )

        cmd = [
            "uv", "run", str(_HERE / "render_shot.py"),
            "--shot", shot_id,
            "--kind", render_kind,
            "--prompt", render_prompt,
            "--duration", str(shot.duration),
        ]
        if mode == "reset" and not target_shots:
            cmd.append("--reset-attempts")
        else:
            cmd.append("--force")

        if media:
            cmd.append("--media")
            cmd.extend(media)
        if voice_arg:
            cmd.extend(["--voice", voice_arg])
        if ratio:
            cmd.extend(["--ratio", ratio])
        if provider:
            cmd.extend(["--provider", provider])
        if no_review:
            cmd.append("--no-review")
        if skip_animatic_gate:
            cmd.append("--skip-animatic-gate")
        if shot.seed is not None:
            cmd.extend(["--seed", str(shot.seed)])
        if shot.negative_prompt:
            cmd.extend(["--negative-prompt", shot.negative_prompt])
        if shot.characters:
            cmd.append("--characters")
            cmd.extend(shot.characters)

        if (not has_animatic_reference
                and prev_last_frame
                and shot.use_prev_last_frame_as_first):
            if Path(prev_last_frame).exists():
                cmd.extend(["--first-frame", prev_last_frame])

        ref_tag = ", storyboard-ref" if has_animatic_reference else ""
        voice_tag = f", {len(voice_refs)} voice-ref" if voice_refs else ""
        print(f"[render] {shot_id} ({render_kind}, {shot.duration}s, "
              f"{len(shot.characters)} chars{ref_tag}{voice_tag})", flush=True)

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600,
            )
            parsed = _parse_render_stdout(proc.stdout)
            if proc.returncode == 0 and parsed:
                parsed["shot_id"] = shot_id
                results.append(parsed)
                prev_last_frame = parsed.get("last_frame_path")
            else:
                stderr_tail = (proc.stderr or "")[-500:].strip()
                print(f"[render_all] {shot_id} failed (exit {proc.returncode}): "
                      f"{stderr_tail[:200]}", file=sys.stderr, flush=True)
                results.append({
                    "shot_id": shot_id,
                    "error": stderr_tail or f"exit {proc.returncode}",
                    "exit_code": proc.returncode,
                })
                prev_last_frame = None
        except subprocess.TimeoutExpired:
            print(f"[render_all] {shot_id} timed out (600s)", file=sys.stderr, flush=True)
            results.append({"shot_id": shot_id, "error": "timeout (600s)"})
            prev_last_frame = None
        except Exception as e:
            print(f"[render_all] {shot_id} exception: {e}", file=sys.stderr, flush=True)
            results.append({"shot_id": shot_id, "error": str(e)})
            prev_last_frame = None

    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--reset", action="store_true", default=True,
                       help="clear state and re-render all (default)")
    group.add_argument("--failed-only", action="store_true",
                       help="only re-render FAILED or winner-less shots")
    group.add_argument("--rejected-only", action="store_true",
                       help="only re-render REJECT verdict shots")
    ap.add_argument("--shot", action="append", default=[],
                    help="render specific shot(s) only; repeatable")
    ap.add_argument("--concurrency", type=int, default=None,
                    help="max parallel chain groups (default: SPARK_VIDEO_MAX_CONCURRENCY or 4)")
    ap.add_argument("--ratio", default=None, help="aspect ratio override (e.g. 9:16)")
    ap.add_argument("--provider", default=None, help="provider override")
    ap.add_argument("--no-review", action="store_true", help="skip auto-review")
    ap.add_argument("--skip-animatic-gate", action="store_true",
                    help="allow video rendering before static storyboard "
                         "reference images are confirmed")
    args = ap.parse_args()

    if args.failed_only:
        mode = "failed-only"
    elif args.rejected_only:
        mode = "rejected-only"
    else:
        mode = "reset"

    ep_dir = _episode_dir()
    sb_path = ep_dir / "storyboard.json"
    state_path = ep_dir / "shots_state.json"
    panels_dir = ep_dir / "storyboard-panels"
    panels_manifest = panels_dir / "panels.json"
    confirmed_path = panels_dir / "CONFIRMED"

    if not sb_path.exists():
        print("ERROR: storyboard.json not found. Run `storyboard.py compile` first.",
              file=sys.stderr)
        return 2
    animatic_gate_skipped = (
        args.skip_animatic_gate
        or os.environ.get("SPARK_VIDEO_SKIP_ANIMATIC_GATE", "").lower()
        in {"1", "true", "yes", "y", "on"}
    )

    if (
        not animatic_gate_skipped
        and (not panels_manifest.exists() or not confirmed_path.exists())
    ):
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

    sb = Storyboard.model_validate(json.loads(sb_path.read_text()))
    provider = args.provider or sb.provider

    cast_index = _build_cast_index(ep_dir)
    cast_voice_index = _build_cast_voice_index(ep_dir)
    set_index = _build_set_index(ep_dir)
    prop_index = _build_prop_index(ep_dir)
    animatic_index = _build_animatic_index(ep_dir)

    shots_by_id = {s.id: s for s in sb.shots}
    scenes_by_id = {sc.id: {"set_id": sc.set_id} for sc in sb.scenes}

    groups = compute_chain_groups(sb)

    if args.shot:
        target_set = set(args.shot)
        groups = [[sid for sid in g if sid in target_set] for g in groups]
        groups = [g for g in groups if g]
        if not groups:
            print(f"ERROR: none of {args.shot} found in storyboard chain groups",
                  file=sys.stderr)
            return 2

    if not animatic_gate_skipped:
        required_ids = [sid for group in groups for sid in group]
        missing_refs = [sid for sid in required_ids if sid not in animatic_index]
        if missing_refs:
            preview = ", ".join(missing_refs[:12])
            more = "" if len(missing_refs) <= 12 else f" (+{len(missing_refs) - 12} more)"
            print(
                "ERROR: confirmed storyboard references are not one-image-per-clip "
                f"or are missing image files for: {preview}{more}. Regenerate with "
                "`uv run scripts/storyboard.py animatic --generate --force`, review, "
                "then confirm again. Storyboard reference images are passed as "
                "reference_image media, never as first_frame.",
                file=sys.stderr,
            )
            return 2

    if mode == "reset" and not args.shot:
        state_path.write_text("{}")
        state = {}
        print("[render_all] state reset — rendering all shots from scratch")
    else:
        state = _load_json(state_path) or {}
        if args.shot:
            print(f"[render_all] re-rendering {args.shot} (preserving version history)")

    max_workers = args.concurrency or int(
        os.environ.get("SPARK_VIDEO_MAX_CONCURRENCY", "4"))

    total_shots = sum(len(g) for g in groups)
    print(f"[render_all] {total_shots} shots in {len(groups)} chain groups, "
          f"concurrency={max_workers}, mode={mode}, "
          f"provider={provider or os.environ.get('SPARK_VIDEO_PROVIDER', 'bl')}")

    all_results = []

    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for i, group in enumerate(groups):
            future = pool.submit(
                _render_chain_group,
                group, ep_dir, shots_by_id, scenes_by_id,
                cast_index, cast_voice_index, set_index, prop_index,
                animatic_index, state,
                mode=mode, target_shots=args.shot or None,
                ratio=args.ratio, provider=provider,
                no_review=args.no_review,
                skip_animatic_gate=animatic_gate_skipped,
            )
            futures[future] = i

        for future in as_completed(futures):
            try:
                results = future.result()
                all_results.extend(results)
            except Exception as e:
                group_idx = futures[future]
                print(f"[render_all] chain group {group_idx} failed: {e}",
                      file=sys.stderr)

    # Ground-truth summary from shots_state.json (render_shot.py is the
    # single writer, so this is authoritative even if our stdout parsing
    # missed a result).
    final_state = _load_json(state_path) or {}
    rendered_ids = set()
    for g in groups:
        rendered_ids.update(g)

    accepted, rejected, failed, skipped = 0, 0, 0, 0
    rejected_details = []
    for sid in sorted(rendered_ids):
        proc_result = next((r for r in all_results if r.get("shot_id") == sid), None)
        if proc_result and proc_result.get("skipped"):
            skipped += 1
            continue
        entry = final_state.get(sid)
        if not entry or not entry.get("attempts"):
            failed += 1
            continue
        if entry.get("winner_version"):
            accepted += 1
            continue
        last_attempt = entry["attempts"][-1]
        if last_attempt.get("status") == "FAILED":
            failed += 1
            continue
        review = last_attempt.get("review", {})
        if review.get("verdict") == "REJECT":
            rejected += 1
            rejected_details.append({
                "shot_id": sid,
                "score": review.get("score"),
                "critique": review.get("critique", ""),
                "vetoed_axes": review.get("vetoed_axes"),
            })
        else:
            failed += 1

    summary = {
        "total": total_shots,
        "accepted": accepted,
        "rejected": rejected,
        "failed": failed,
        "skipped": skipped,
    }
    if rejected_details:
        summary["rejected_shots"] = rejected_details

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
