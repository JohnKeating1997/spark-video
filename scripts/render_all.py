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


def _normalise_manifest_image(image: str) -> str | None:
    if _is_remote_media_ref(image):
        return image
    path = Path(image).expanduser()
    try:
        return str(path.resolve()) if path.exists() else None
    except OSError:
        return None


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
    shots_by_id: dict,
    scenes_by_id: dict,
    cast_index: dict,
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
        print(f"[render] {shot_id} ({render_kind}, {shot.duration}s, "
              f"{len(shot.characters)} chars{ref_tag})", flush=True)

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
                group, shots_by_id, scenes_by_id,
                cast_index, set_index, prop_index, animatic_index, state,
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
