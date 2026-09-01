# /// script
# requires-python = ">=3.10"
# dependencies = ["pydantic>=2.5"]
# ///
"""
storyboard.py — storyboard operations (validate / compile / estimate / graph).

Subcommands:
    validate            Validate per-scene JSON fragments and/or full storyboard.json
    compile             Merge scenes/scene-*.{md,json} → script.md + storyboard.json
    animatic            Build/generate/confirm per-shot static storyboard references
    estimate            Print render duration & cost estimate. Exit 2 if over budget.
    graph               Print chain-DAG parallel groups (JSON array of arrays).

All commands respect SPARK_VIDEO_PROJECT / SPARK_VIDEO_EPISODE env vars.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from lib.env import load_pwd_dotenv                  # noqa: E402
from lib.storyboard import Storyboard, Scene, Shot  # noqa: E402
from lib.render_graph import compute_chain_groups   # noqa: E402
from lib.cli import active_wan_site, bl_cmd, wan_cmd, wan_media_tag  # noqa: E402
from lib.prompt_compiler import (  # noqa: E402
    art_direction_conflicts,
    compatible_art_direction,
    reference_treatment_instruction,
    rendering_instruction,
    require_compatible_art_direction,
    resolve_visual_medium,
    validate_reference_tags,
)
from lib.shot_contract import (  # noqa: E402
    approval_contract,
    contract_mismatches,
    contract_fingerprint,
    storyboard_contract_fingerprint,
)

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


# ------------------------------------------------------------------ validate

def cmd_validate(args: argparse.Namespace) -> int:
    ep_dir = _episode_dir()
    if args.scene is not None:
        # Validate one scene fragment
        sf = ep_dir / "scenes" / f"scene-{int(args.scene):02d}.json"
        if not sf.exists():
            print(f"ERROR: {sf} not found", file=sys.stderr)
            return 2
        data = json.loads(sf.read_text())
        # Construct a minimal Storyboard to validate the fragment
        sb_data = {
            "title": "validate-only",
            "scenes": [data["scene"]],
            "shots": data["shots"],
        }
        try:
            Storyboard.model_validate(sb_data)
        except Exception as e:
            print(f"VALIDATION FAILED for scene {args.scene}:\n{e}",
                  file=sys.stderr)
            return 1
        print(f"OK: scene-{int(args.scene):02d}.json validates")
        return 0

    # Validate full storyboard.json
    sb_path = ep_dir / "storyboard.json"
    if not sb_path.exists():
        print(f"ERROR: {sb_path} not found. Run `storyboard.py compile` first.",
              file=sys.stderr)
        return 2
    try:
        sb = Storyboard.model_validate(json.loads(sb_path.read_text()))
    except Exception as e:
        print(f"VALIDATION FAILED:\n{e}", file=sys.stderr)
        return 1

    # Lint warnings (non-fatal)
    warns = _lint(sb, ep_dir)
    for w in warns:
        print(f"WARN: {w}", file=sys.stderr)
    print(f"OK: {sb_path} validates ({len(sb.scenes)} scenes, "
          f"{len(sb.shots)} shots, {len(warns)} warnings)")
    return 0


def _lint(sb: Storyboard, ep_dir: Path) -> list[str]:
    """Cross-fragment lints that pure schema can't catch."""
    warns: list[str] = list(sb.lint())

    lore_front = _read_lore_front(ep_dir)
    try:
        project_medium = resolve_visual_medium(
            project_default=lore_front.get("visual_medium"),
            fallback_text=" ".join(
                str(lore_front.get(key) or "")
                for key in ("visual_style", "mood_anchor")
            ),
        )
        warns.extend(art_direction_conflicts(lore_front, project_medium))
    except ValueError as exc:
        warns.append(str(exc))

    # Load manifests if present
    cast_path = ep_dir / "cast.json"
    set_path = ep_dir / "movie_set.json"
    prop_path = ep_dir / "props.json"
    cast = _safe_load_json(cast_path)
    sets = _safe_load_json(set_path)
    props = _safe_load_json(prop_path)
    cast_names = _extract_names(cast)
    set_names = _extract_names(sets)
    prop_names = _extract_names(props)

    # Shot-level lints
    for shot in sb.shots:
        # Unknown characters
        for ch in (shot.characters or []):
            if cast_names and ch not in cast_names:
                warns.append(f"{shot.id}: character '{ch}' not in cast.json")
        # Unknown props
        for p in (shot.props or []):
            if prop_names and p not in prop_names:
                warns.append(f"{shot.id}: prop '{p}' not in props.json")
        # Props on t2v/i2v
        if shot.props and shot.kind in ("t2v", "i2v"):
            warns.append(f"{shot.id}: props attached to {shot.kind} shot "
                         "(no media[] slot — silently dropped)")
        # Unknown set_id
        sid = shot.set_id
        if sid and set_names and sid not in set_names:
            warns.append(f"{shot.id}: set_id '{sid}' not in movie_set.json")

    # Scene-level
    for sc in sb.scenes:
        if sc.set_id and set_names and sc.set_id not in set_names:
            warns.append(f"scene {sc.id}: set_id '{sc.set_id}' not in movie_set.json")

    # Dialog duration vs shot duration
    _CHARS_PER_SEC = 4.0
    _BUFFER_S = 2  # leave room for action/reaction
    for shot in sb.shots:
        dialog = _extract_dialog(shot.prompt)
        if dialog:
            est_s = len(dialog) / _CHARS_PER_SEC
            avail_s = shot.duration - _BUFFER_S
            if est_s > shot.duration:
                warns.append(
                    f"{shot.id}: dialog too long for duration — "
                    f"~{len(dialog)} chars ≈ {est_s:.0f}s speech, "
                    f"but shot is only {shot.duration}s "
                    f"(will be truncated; split the dialog or increase duration)")
            elif est_s > avail_s:
                warns.append(
                    f"{shot.id}: dialog tight — "
                    f"~{len(dialog)} chars ≈ {est_s:.0f}s speech in a {shot.duration}s shot "
                    f"(leaves <{_BUFFER_S}s for action; consider splitting)")

    # Chain-group lighting consistency
    groups = compute_chain_groups(sb)
    shot_by_id = {s.id: s for s in sb.shots}
    scene_by_id = {sc.id: sc for sc in sb.scenes}
    for group in groups:
        sets_seen = set()
        for sid in group:
            shot = shot_by_id.get(sid)
            if not shot or shot.kind != "r2v":
                continue
            effective_set = shot.set_id
            if effective_set is None:
                # inherit from scene
                sc = scene_by_id.get(shot.scene)
                effective_set = sc.set_id if sc else None
            if effective_set:
                sets_seen.add(effective_set)
        if len(sets_seen) > 1:
            warns.append(f"chain group {group[0]}..{group[-1]} mixes set_ids "
                         f"{sorted(sets_seen)} (lighting consistency rule: split the chain)")

    # Time-of-day / setting continuity within each scene
    for sc in sb.scenes:
        scene_shots = [s for s in sb.shots if s.scene == sc.id]
        if not scene_shots:
            continue

        # Detect set_id time-of-day
        effective_set = sc.set_id or ""
        set_tod = _detect_time_of_day_from_set(effective_set)

        shot_tods = []
        for shot in scene_shots:
            prompt_tod = _detect_time_of_day(shot.prompt)
            shot_set = shot.set_id or effective_set or ""
            shot_set_tod = _detect_time_of_day_from_set(shot_set)

            # Prompt vs its own set_id
            if prompt_tod and shot_set_tod and prompt_tod != shot_set_tod:
                warns.append(
                    f"{shot.id}: time-of-day conflict — prompt says "
                    f"'{prompt_tod}' but set_id '{shot_set}' implies "
                    f"'{shot_set_tod}'")

            # Prompt vs scene set_id
            if prompt_tod and set_tod and prompt_tod != set_tod and not shot.set_id:
                warns.append(
                    f"{shot.id}: time-of-day conflict — prompt says "
                    f"'{prompt_tod}' but scene set '{effective_set}' implies "
                    f"'{set_tod}'")

            if prompt_tod:
                shot_tods.append((shot.id, prompt_tod))

        # Cross-shot consistency within the scene
        if len(shot_tods) >= 2:
            tods_set = set(t for _, t in shot_tods)
            if len(tods_set) > 1:
                examples = ", ".join(f"{sid}={t}" for sid, t in shot_tods[:4])
                warns.append(
                    f"scene {sc.id}: mixed time-of-day across shots "
                    f"({examples}) — verify this is intentional")

    return warns


def _llm_continuity_check(sb: Storyboard, ep_dir: Path) -> list[str]:
    """Use LLM to check narrative continuity across shots within each scene.

    Best-effort: returns [] on any failure (API down, timeout, parse error).
    Never blocks compile.
    """
    try:
        bl_prefix = bl_cmd(_HERE.parent)
    except FileNotFoundError:
        return []

    lore_front = _read_lore_front(ep_dir)
    lore_context = {
        key: lore_front.get(key)
        for key in (
            "title", "genre", "visual_medium", "visual_style", "mood_anchor",
            "forbidden", "imagery_system",
        )
        if lore_front.get(key)
    }

    # Keep each shot complete. Truncating individual prompts creates false
    # continuity failures; batching/timeout is the caller's budget boundary.
    scene_payloads: list[dict] = []
    shot_by_scene: dict[str, list] = {}
    for s in sb.shots:
        shot_by_scene.setdefault(s.scene, []).append(s)

    for sc in sb.scenes:
        shots = shot_by_scene.get(sc.id, [])
        if not shots:
            continue
        scene_payloads.append({
            "id": sc.id,
            "name": sc.name,
            "description": sc.description,
            "set_id": sc.set_id,
            "shots": [
                {
                    "id": shot.id,
                    "characters": shot.characters,
                    "props": shot.props,
                    "set_id": shot.set_id,
                    "narrative_purpose": shot.narrative_purpose,
                    "use_prev_last_frame_as_first": shot.use_prev_last_frame_as_first,
                    "prompt": shot.prompt,
                }
                for shot in shots
            ],
        })

    if lore_front.get("prompt_language") == "en":
        prompt = (
            "You are a film screenplay continuity reviewer. Below is a short-film storyboard grouped by scene.\n"
            "Report only genuine problems, one per line, formatted as `[SHOT_ID] problem description`.\n"
            "If there are no problems, output a blank line.\n\n"
            "Check for:\n"
            "1. Time contradictions within a scene.\n"
            "2. Location contradictions without a stated transition.\n"
            "3. Character-action logic contradictions.\n"
            "4. Action-continuity problems across chained shots.\n"
            "5. Dialogue that conflicts with the scene setting.\n\n"
            "Do not report truncation: every prompt in the JSON below is complete.\n\n"
            "World context:\n"
            + json.dumps(lore_context, ensure_ascii=False, indent=2)
            + "\n\nStoryboard:\n"
            + json.dumps(scene_payloads, ensure_ascii=False, indent=2)
        )
    else:
        prompt = (
            "你是一个影视剧本连贯性审查员。下面是一部短剧的分镜列表，按场景分组。\n"
            "请检查以下问题，只输出有问题的条目，每条一行，格式: `[SHOT_ID] 问题描述`。\n"
            "如果没有问题，输出一个空行。\n\n"
            "检查项：\n"
            "1. 同一场景内时间矛盾（如一个镜头白天，下一个镜头深夜）\n"
            "2. 同一场景内地点矛盾（如一个镜头在办公室，下一个突然在户外但没有转场说明）\n"
            "3. 角色行为逻辑矛盾（如角色已离开但下一个镜头又出现）\n"
            "4. 动作连贯性问题（如前一个镜头角色站着，下一个镜头突然坐着，且是链式续接）\n"
            "5. 台词内容与场景设定冲突\n\n"
            "不要因为字段或句子在显示中被截断而报错；下面 JSON 中的 prompt 均为完整原文。\n\n"
            "世界设定:\n"
            + json.dumps(lore_context, ensure_ascii=False, indent=2)
            + "\n\n分镜列表:\n"
            + json.dumps(scene_payloads, ensure_ascii=False, indent=2)
        )

    try:
        proc = subprocess.run(
            bl_prefix + ["text", "chat", "--model", "qwen-plus",
                         "--message", prompt],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            return []
        # Parse output — extract lines starting with [S
        output = proc.stdout
        # Try to extract from JSON envelope
        try:
            envelope = json.loads(output)
            choices = envelope.get("choices") or []
            if choices:
                content = choices[0].get("message", {}).get("content", "")
            else:
                content = output
        except (json.JSONDecodeError, ValueError):
            content = output

        warns = []
        for line in content.strip().splitlines():
            line = line.strip()
            if not line or line == "无" or line == "没有问题":
                continue
            if line.startswith("[S") or line.startswith("- [S") or line.startswith("S0"):
                warns.append(line.lstrip("- "))
            elif "S0" in line and ("矛盾" in line or "冲突" in line or "不一致" in line
                                   or "问题" in line):
                warns.append(line.lstrip("- "))
        return warns
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []


_DAY_KEYWORDS = ("白天", "阳光", "日光", "晴天", "日照", "午后", "上午", "下午", "daylight")
_NIGHT_KEYWORDS = ("夜晚", "夜色", "深夜", "黑夜", "月光", "凌晨", "夜市", "霓虹")


def _detect_time_of_day(text: str) -> str | None:
    """Detect day/night from prompt text. Returns 'day', 'night', or None."""
    has_day = any(k in text for k in _DAY_KEYWORDS)
    has_night = any(k in text for k in _NIGHT_KEYWORDS)
    if has_day and not has_night:
        return "day"
    if has_night and not has_day:
        return "night"
    return None


def _detect_time_of_day_from_set(set_id: str) -> str | None:
    """Detect day/night from set_id naming convention (e.g. 'office-day')."""
    s = set_id.lower()
    if any(k in s for k in ("day", "白天", "日", "morning", "afternoon")):
        return "day"
    if any(k in s for k in ("night", "夜", "evening", "凌晨")):
        return "night"
    return None


def _extract_dialog(prompt: str) -> str | None:
    """Extract dialog text from a shot prompt (after '说道：' or '说道:')."""
    import re
    m = re.search(r"说道[：:](.+?)(?:真人写实|$)", prompt, re.DOTALL)
    if not m:
        return None
    dialog = m.group(1).strip().rstrip("。！？，、")
    return dialog if len(dialog) > 2 else None


def _safe_load_json(p: Path) -> dict | None:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def _extract_names(manifest: dict | None) -> set[str]:
    if not manifest:
        return set()
    # cast.json / movie_set.json / props.json share `{"<name>": {...}}` shape
    if isinstance(manifest, dict):
        # Some manifests nest under a top-level key
        for key in ("cast", "sets", "props", "entries", "items"):
            if isinstance(manifest.get(key), dict):
                return set(manifest[key].keys())
        return set(manifest.keys())
    return set()


# ------------------------------------------------------------------- compile

def cmd_compile(args: argparse.Namespace) -> int:
    ep_dir = _episode_dir()
    scenes_dir = ep_dir / "scenes"
    if not scenes_dir.exists():
        print(f"ERROR: {scenes_dir} not found", file=sys.stderr)
        return 2

    md_files = sorted(scenes_dir.glob("scene-*.md"))
    json_files = sorted(scenes_dir.glob("scene-*.json"))

    if not md_files:
        print("ERROR: no scene-*.md found", file=sys.stderr)
        return 1
    if len(json_files) != len(md_files):
        print(f"WARN: {len(md_files)} md vs {len(json_files)} json — "
              "director may not be done", file=sys.stderr)

    # Merge .md → script.md
    script_md = ep_dir / "script.md"
    parts = []
    proj = os.environ.get("SPARK_VIDEO_PROJECT")
    ep = os.environ.get("SPARK_VIDEO_EPISODE")
    parts.append(f"# {proj} / {ep}\n")
    for f in md_files:
        parts.append(f.read_text())
        parts.append("\n\n---\n\n")
    script_md.write_text("".join(parts).rstrip() + "\n")
    print(f"wrote {script_md}", file=sys.stderr)

    # Merge .json → storyboard.json
    scenes: list[dict] = []
    shots: list[dict] = []
    for f in json_files:
        try:
            frag = json.loads(f.read_text())
        except json.JSONDecodeError as e:
            print(f"ERROR: {f.name} is not valid JSON: {e}", file=sys.stderr)
            return 1
        scenes.append(frag["scene"])
        shots.extend(frag["shots"])

    sb_data = {
        "title": proj or "untitled",
        "project_id": proj,
        "scenes": scenes,
        "shots": shots,
        "mode": args.mode,
        "provider": args.provider,
        "video_model": args.video_model,
    }
    lore_front = _read_lore_front(ep_dir)
    raw_target_duration = lore_front.get("duration_target_s")
    if raw_target_duration is not None:
        try:
            sb_data["target_duration_s"] = int(str(raw_target_duration).strip())
        except ValueError:
            print(
                "ERROR: lore.md duration_target_s must be an integer, got "
                f"{raw_target_duration!r}",
                file=sys.stderr,
            )
            return 1
    if args.narrator_voice:
        sb_data["narrator_voice"] = args.narrator_voice
    audio_cfg_path = ep_dir / "audio-config.json"
    if audio_cfg_path.exists():
        sb_data["audio"] = json.loads(audio_cfg_path.read_text(encoding="utf-8"))
    if args.audio_mode:
        policy = {
            "presenter_voiceover": "strip_all",
            "native_dialogue": "keep",
            "hybrid": "per_shot",
        }[args.audio_mode]
        sb_data["audio"] = {
            "mode": args.audio_mode,
            "presenter": args.presenter,
            "voice": args.voice or args.narrator_voice,
            "model_audio_policy": policy,
            "subtitle_mode": args.subtitle_mode,
        }

    # Apply BGM config if present
    bgm_cfg_path = ep_dir / "bgm-config.json"
    if bgm_cfg_path.exists():
        sb_data["bgm"] = json.loads(bgm_cfg_path.read_text())

    try:
        sb = Storyboard.model_validate(sb_data)
    except Exception as e:
        print(f"VALIDATION FAILED during compile:\n{e}", file=sys.stderr)
        return 1

    sb_path = ep_dir / "storyboard.json"
    sb_path.write_text(json.dumps(sb.model_dump(), ensure_ascii=False, indent=2))
    print(f"wrote {sb_path} ({len(sb.scenes)} scenes, {len(sb.shots)} shots)",
          file=sys.stderr)

    # LLM continuity check (best-effort — never blocks compile)
    continuity_warns = _llm_continuity_check(sb, ep_dir)
    if continuity_warns:
        print(f"\n{'='*60}", file=sys.stderr)
        print("CONTINUITY ISSUES (from LLM review):", file=sys.stderr)
        for w in continuity_warns:
            print(f"  ⚠ {w}", file=sys.stderr)
        print(f"{'='*60}\n", file=sys.stderr)

    return 0


# ------------------------------------------------------------------ animatic

_REMOTE_MEDIA_PREFIXES = ("http://", "https://", "asset://", "data:")
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _is_remote_media_ref(value: str) -> bool:
    return value.startswith(_REMOTE_MEDIA_PREFIXES)


def _scan_first_image(folder: Path) -> str | None:
    if not folder.is_dir():
        return None
    for f in sorted(folder.iterdir()):
        if f.is_file() and f.suffix.lower() in _IMAGE_EXTS:
            return str(f)
    return None


def _normalise_media_ref(value: str) -> str | None:
    if _is_remote_media_ref(value):
        return value
    path = Path(value).expanduser()
    try:
        return str(path.resolve()) if path.exists() else None
    except OSError:
        return None


def _asset_records(data, plural_key: str) -> list[dict]:
    if not isinstance(data, dict):
        return []
    if isinstance(data.get(plural_key), list):
        return [x for x in data[plural_key] if isinstance(x, dict)]
    if isinstance(data.get(plural_key), dict):
        return [x for x in data[plural_key].values() if isinstance(x, dict)]
    return [x for x in data.values() if isinstance(x, dict)]


def _first_record_image(record: dict) -> str | None:
    value = record.get("image_url")
    if isinstance(value, str) and value:
        return value
    for value in record.get("image_urls", []) or []:
        if isinstance(value, str) and value:
            return value
    for key in ("image_local", "image", "path"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    for value in record.get("images", []) or []:
        if isinstance(value, str) and value:
            return value
    return None


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
        data = _safe_load_json(data_path)
        for record in _asset_records(data, plural_key):
            name = record.get("name")
            image = _first_record_image(record)
            ref = _normalise_media_ref(image) if isinstance(image, str) else None
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


def _scene_set_id(sb: Storyboard, scene_id: str | None) -> str | None:
    if not scene_id:
        return None
    for scene in sb.scenes:
        if scene.id == scene_id:
            return scene.set_id
    return None


def _add_reference_entry(
    refs: list[dict[str, str]],
    seen: set[str],
    *,
    path: str | None,
    kind: str,
    name: str,
    instruction: str,
) -> None:
    if not path or path in seen:
        return
    seen.add(path)
    refs.append({
        "path": path,
        "kind": kind,
        "name": name,
        "instruction": instruction,
    })


def _animatic_reference_entries(
    ep_dir: Path,
    sb: Storyboard,
    shots: list[Shot],
    *,
    render_style: str,
) -> list[dict[str, str]]:
    cast_index = _build_asset_index(
        ep_dir, json_name="cast.json", plural_key="characters", folder_name="cast"
    )
    set_index = _build_asset_index(
        ep_dir, json_name="movie_set.json", plural_key="sets", folder_name="movie-set"
    )
    prop_index = _build_asset_index(
        ep_dir, json_name="props.json", plural_key="props", folder_name="props"
    )
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for shot in shots:
        for name in shot.characters or []:
            rendering_rule = reference_treatment_instruction(
                render_style, subject="character"
            )
            _add_reference_entry(
                refs,
                seen,
                path=cast_index.get(name),
                kind="character",
                name=name,
                instruction=(
                    f"Authoritative character reference for {name}. Strictly "
                    "preserve identity, face shape, hairstyle, costume, "
                    "accessories, body type, silhouette, and apparent age. "
                    "Do not redesign or replace the hairstyle or costume. "
                    + rendering_rule
                ),
            )
        set_id = shot.set_id or _scene_set_id(sb, shot.scene)
        if set_id:
            set_rendering_rule = reference_treatment_instruction(
                render_style, subject="location"
            )
            _add_reference_entry(
                refs,
                seen,
                path=set_index.get(set_id),
                kind="location",
                name=set_id,
                instruction=(
                    f"Authoritative location reference for {set_id}. Preserve architecture, "
                    "spatial layout, period details, lighting mood, and main "
                    "environmental elements. Do not redesign the layout. "
                    + set_rendering_rule
                ),
            )
        for name in shot.props or []:
            prop_rendering_rule = reference_treatment_instruction(
                render_style, subject="prop"
            )
            _add_reference_entry(
                refs,
                seen,
                path=prop_index.get(name),
                kind="prop",
                name=name,
                instruction=(
                    f"Authoritative prop reference for {name}. Preserve shape, "
                    "material, color, texture, and scale. Do not redesign it "
                    "or override the shot action. " + prop_rendering_rule
                ),
            )
    return refs


def _animatic_render_style(
    shots: list[Shot],
    lore_front: dict[str, str | list[str]],
) -> str:
    return resolve_visual_medium(
        project_default=lore_front.get("visual_medium"),
        shot_overrides=[shot.animatic_style for shot in shots],
        fallback_text=" ".join(
            (shot.animatic_prompt or shot.prompt) for shot in shots
        ),
    )


def _validate_animatic_reference_tags(
    prompt: str,
    *,
    reference_count: int,
    site: str,
) -> None:
    first_tag = wan_media_tag("image", 1, site=site)
    validate_reference_tags(
        prompt,
        tag_prefix=first_tag[:-1],
        reference_count=reference_count,
    )

def _read_lore_front(ep_dir: Path) -> dict[str, str | list[str]]:
    """Crude front-matter reader for project lore + episode override."""
    def parse_front(lore_path: Path) -> dict[str, str | list[str]]:
        if not lore_path.exists():
            return {}
        text = lore_path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return {}
        lines = text.splitlines()
        front: dict[str, str | list[str]] = {}
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if ":" not in line or line.startswith((" ", "\t")):
                continue
            key, raw = line.split(":", 1)
            key = key.strip()
            val = raw.strip().strip("'\"")
            if not val:
                continue
            if val.startswith("[") and val.endswith("]"):
                items = [x.strip().strip("'\"") for x in val[1:-1].split(",")]
                front[key] = [x for x in items if x]
            else:
                front[key] = val
        return front

    front = parse_front(ep_dir.parent / "lore.md")
    front.update(parse_front(ep_dir / "lore.md"))
    return front

def _chunks(seq: list[Shot], n: int) -> list[list[Shot]]:
    return [seq[i:i + n] for i in range(0, len(seq), n)]


def _targeted_animatic_panels(
    panels: list[dict], target_shots: list[str] | None,
) -> list[dict]:
    """Return only panels containing an explicitly targeted shot."""
    if not target_shots:
        return panels
    targets = set(target_shots)
    return [
        panel for panel in panels
        if targets.intersection(str(shot_id) for shot_id in panel.get("shots", []))
    ]


def _animatic_panel_prompt(
    *,
    ep_dir: Path,
    sb: Storyboard,
    shots: list[Shot],
    panel_no: int,
    panel_count: int,
    lore_front: dict[str, str | list[str]],
) -> str:
    del panel_no, panel_count  # Panel order is manifest metadata, not image content.
    render_style = _animatic_render_style(shots, lore_front)
    require_compatible_art_direction(lore_front, render_style)
    style_bits = compatible_art_direction(lore_front, render_style)

    lines = ["Task:", "Create one static storyboard reference image."]
    rendering = rendering_instruction(render_style)
    lines.extend([f"Rendering: {rendering}"])
    if style_bits:
        lines.append("Art direction: " + "; ".join(style_bits) + ".")
    reference_entries = _animatic_reference_entries(
        ep_dir, sb, shots, render_style=render_style
    )
    if reference_entries:
        site = active_wan_site(_HERE.parent)
        lines.extend([
            "",
            "References:",
        ])
        for idx, ref in enumerate(reference_entries, 1):
            tag = wan_media_tag("image", idx, site=site)
            lines.append(f"{tag}: {ref['instruction']}")
        lines.extend([
            "Reference images are authoritative for character appearance and environment. Shot text controls composition, action, and only explicitly declared style changes. The tags match uploaded-image order.",
        ])
    lines.extend(["", "Shot:"])
    for shot in shots:
        panel_prompt = (shot.animatic_prompt or shot.prompt).strip()
        panel_prompt = " ".join(panel_prompt.split())
        lines.append(panel_prompt)
    lines.extend([
        "",
        "Constraints:",
        "One clear still composition. Preserve reference continuity. No speech "
        "bubbles, subtitles, captions, UI, borders, or panel labels.",
    ])
    prompt = "\n".join(lines).strip() + "\n"
    if reference_entries:
        _validate_animatic_reference_tags(
            prompt,
            reference_count=len(reference_entries),
            site=site,
        )
    return prompt


def _find_generated_panel_images(panel_dir: Path, prefix: str) -> list[Path]:
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    exact_stems = {prefix, f"{prefix}-openai"}
    return sorted(
        p for p in panel_dir.glob(f"{prefix}*")
        if (
            p.is_file()
            and p.suffix.lower() in exts
            and (
                p.stem in exact_stems
                or p.stem.startswith(f"{prefix}-candidate-")
            )
        )
    )


def _wan_json(stdout: str) -> dict:
    text = stdout.strip()
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


def _generated_image_urls(payload: dict) -> list[str | None]:
    """Return Wan result URLs in the same order as result indices."""
    results = payload.get("result") or []
    if not results and isinstance(payload.get("task"), dict):
        results = payload["task"].get("taskResult") or []
    urls: list[str | None] = []
    for result in results:
        if not isinstance(result, dict):
            urls.append(None)
            continue
        image_url = None
        for key in (
            "downloadUrl",
            "urlWithoutLogo",
            "url",
            "resultImage",
            "originImage",
        ):
            value = result.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                image_url = value
                break
        urls.append(image_url)
    return urls


def _generate_wan_panel(item: dict, *, model: str, ratio: str,
                        panel_dir: Path, candidate_start: int = 1,
                        max_candidates: int = 1,
                        ) -> list[tuple[Path, str | None, str | None]]:
    prompt = Path(item["prompt"]).read_text(encoding="utf-8")
    refs = [
        str(ref["path"])
        for ref in item.get("reference_images", [])
        if isinstance(ref, dict) and ref.get("path")
    ]
    with tempfile.TemporaryDirectory(prefix="spark-video-panel-") as temp_dir:
        if refs:
            cmd = wan_cmd(_HERE.parent) + [
                "image2image", "--images", ",".join(refs),
                "--generation-mode", "reference", "--prompt", prompt,
            ]
        else:
            cmd = wan_cmd(_HERE.parent) + ["text2image", "--prompt", prompt]
        if model:
            cmd += ["--model", model]
        cmd += [
            "--ratio", ratio, "--resolution", "2K", "--wait", "--save",
            "--save-dir", temp_dir, "--timeout", "600", "--output", "json",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=630)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout).strip()[-2000:])
        payload = _wan_json(proc.stdout)
        image_urls = _generated_image_urls(payload)
        saved: list[tuple[int, Path, str | None]] = []
        seen: set[Path] = set()
        for fallback_index, value in enumerate(payload.get("savedFiles") or []):
            raw = value.get("path") if isinstance(value, dict) else value
            raw_index = value.get("index", fallback_index) if isinstance(value, dict) else fallback_index
            if isinstance(raw, str):
                path = Path(raw).expanduser().resolve()
                try:
                    result_index = int(raw_index)
                except (TypeError, ValueError):
                    result_index = fallback_index
                if (path.exists() and path.suffix.lower()
                        in {".png", ".jpg", ".jpeg", ".webp"}):
                    url = image_urls[result_index] if 0 <= result_index < len(image_urls) else None
                    saved.append((result_index, path, url))
                    seen.add(path)
        for path in sorted(Path(temp_dir).iterdir()):
            resolved = path.resolve()
            if (resolved not in seen and path.exists() and path.suffix.lower()
                    in {".png", ".jpg", ".jpeg", ".webp"}):
                saved.append((len(saved), resolved, None))
        saved.sort(key=lambda value: value[0])
        if not saved:
            raise RuntimeError(
                f"wan returned no saved image; taskId={payload.get('taskId', 'unknown')}"
            )
        task_id = payload.get("taskId")
        generated = []
        for offset, (_index, source, image_url) in enumerate(saved[:max_candidates]):
            candidate_no = candidate_start + offset
            destination = panel_dir / (
                f"{item['id']}-candidate-{candidate_no:02d}{source.suffix.lower()}"
            )
            shutil.copy2(source, destination)
            generated.append((
                destination,
                image_url,
                str(task_id) if task_id else None,
            ))
        return generated


def cmd_animatic(args: argparse.Namespace) -> int:
    ep_dir = _episode_dir()
    sb_path = ep_dir / "storyboard.json"
    if not sb_path.exists():
        print("ERROR: storyboard.json not found. Run `storyboard.py compile` first.",
              file=sys.stderr)
        return 2

    panel_dir = ep_dir / "storyboard-panels"
    panel_dir.mkdir(parents=True, exist_ok=True)
    confirm_path = panel_dir / "CONFIRMED"

    manifest_path = panel_dir / "panels.json"

    if args.select:
        if not manifest_path.exists():
            print(
                f"ERROR: {manifest_path} missing. Run "
                "`uv run scripts/storyboard.py animatic` first.",
                file=sys.stderr,
            )
            return 2
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR: cannot read {manifest_path}: {exc}", file=sys.stderr)
            return 2
        panels = {
            item.get("shots", [None])[0]: item
            for item in manifest.get("panels", []) or []
            if isinstance(item, dict) and len(item.get("shots") or []) == 1
        }
        for decision in args.select:
            if "=" not in decision:
                print(
                    f"ERROR: invalid selection {decision!r}; expected SHOT=CANDIDATE",
                    file=sys.stderr,
                )
                return 2
            shot_id, candidate_id = (part.strip() for part in decision.split("=", 1))
            panel = panels.get(shot_id)
            if panel is None:
                print(f"ERROR: unknown storyboard shot {shot_id!r}", file=sys.stderr)
                return 2
            candidate_ids = {
                str(candidate.get("id"))
                for candidate in panel.get("candidates", []) or []
                if isinstance(candidate, dict) and candidate.get("id")
            }
            if candidate_id not in candidate_ids:
                print(
                    f"ERROR: unknown candidate {candidate_id!r} for {shot_id}; "
                    f"choose one of {sorted(candidate_ids)}",
                    file=sys.stderr,
                )
                return 2
            panel["selected_candidate"] = candidate_id
        manifest["confirmed"] = False
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if confirm_path.exists():
            confirm_path.unlink()
        print(f"saved storyboard selections to {manifest_path}")
        if not args.confirm:
            return 0

    if args.confirm:
        if not manifest_path.exists():
            print(
                f"ERROR: {manifest_path} missing. Run "
                "`uv run scripts/storyboard.py animatic` first.",
                file=sys.stderr,
            )
            return 2
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        missing: list[str] = []
        invalid: list[str] = []
        storyboard_data = json.loads(sb_path.read_text(encoding="utf-8"))
        expected_shots = {
            shot.get("id")
            for shot in storyboard_data.get("shots", []) or []
            if isinstance(shot, dict) and shot.get("id")
        }
        manifest_shots: set[str] = set()
        stale_contracts = contract_mismatches(storyboard_data, manifest)
        for panel in manifest.get("panels", []) or []:
            shot_id = str((panel.get("shots") or [panel.get("id")])[0])
            manifest_shots.add(shot_id)
            selected = panel.get("selected_candidate")
            candidates = {
                candidate.get("id"): candidate
                for candidate in panel.get("candidates", []) or []
                if isinstance(candidate, dict) and candidate.get("id")
            }
            if not selected:
                missing.append(shot_id)
            elif selected not in candidates or not (
                candidates[selected].get("image_url")
                or candidates[selected].get("image")
            ):
                invalid.append(shot_id)
        missing.extend(sorted(expected_shots - manifest_shots))
        if missing or invalid or stale_contracts:
            detail = []
            if missing:
                detail.append(f"not selected: {', '.join(missing)}")
            if invalid:
                detail.append(f"invalid selection: {', '.join(invalid)}")
            if stale_contracts:
                detail.append(
                    "stale shot contract: " + ", ".join(stale_contracts)
                )
            print(
                "ERROR: every shot must select one storyboard candidate before "
                f"confirmation ({'; '.join(detail)}).",
                file=sys.stderr,
            )
            return 2
        confirm_path.write_text(
            "User approved per-shot static storyboard reference images for video rendering.\n",
            encoding="utf-8",
        )
        manifest["confirmed"] = True
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"confirmed {panel_dir}")
        return 0

    if args.unconfirm:
        if confirm_path.exists():
            confirm_path.unlink()
        print(f"removed confirmation marker: {confirm_path}")
        return 0

    sb = Storyboard.model_validate(json.loads(sb_path.read_text(encoding="utf-8")))
    target_shots = list(dict.fromkeys(args.shot or []))
    if target_shots:
        storyboard_shots = {shot.id for shot in sb.shots}
        unknown_shots = [
            shot_id for shot_id in target_shots
            if shot_id not in storyboard_shots
        ]
        if unknown_shots:
            print(
                "ERROR: requested animatic shot(s) not found in storyboard: "
                + ", ".join(unknown_shots),
                file=sys.stderr,
            )
            return 2
    lore_front = _read_lore_front(ep_dir)
    if args.shots_per_image != 1:
        print(
            "WARN: --shots-per-image is deprecated; animatic now always "
            "generates one static storyboard reference image per clip.",
            file=sys.stderr,
        )
    groups = _chunks(sb.shots, 1)

    previous_manifest: dict = {}
    if manifest_path.exists():
        try:
            previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_manifest = {}
    previous_panels = {
        item.get("id"): item
        for item in previous_manifest.get("panels", []) or []
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }

    manifest: dict = {
        "storyboard": str(sb_path),
        "shots_per_image": 1,
        "mode": "per_shot_reference_image",
        "model": args.model,
        "size": args.size,
        "panels": [],
        "confirmed": confirm_path.exists(),
        "storyboard_contract_fingerprint": storyboard_contract_fingerprint(
            sb.model_dump(mode="json")
        ),
    }
    contracts_changed: list[str] = []
    episode_contract_changed = bool(
        previous_manifest
        and previous_manifest.get("storyboard_contract_fingerprint")
        != manifest["storyboard_contract_fingerprint"]
    )
    if episode_contract_changed:
        contracts_changed.append("<storyboard>")

    shell_lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f"cd {shlex.quote(str(Path.cwd()))}",
        f"export SPARK_VIDEO_PROJECT={shlex.quote(os.environ.get('SPARK_VIDEO_PROJECT', ''))}",
        f"export SPARK_VIDEO_EPISODE={shlex.quote(os.environ.get('SPARK_VIDEO_EPISODE', ''))}",
        "export SPARK_VIDEO_PHASE=animatic",
        "",
    ]
    openai_image_model = args.model.strip().lower() in {
        "openai",
        "openai-image",
        "openai-image-placeholder",
        "gpt-image-1",
    }
    if openai_image_model:
        shell_lines.extend([
            "echo 'This episode is configured for OpenAI image generation.'",
            "echo 'Use the per-shot .prompt.txt files plus panels.json reference_images order with the OpenAI image generator.'",
            "echo 'The wan-cli image helper is intentionally disabled for this animatic run.'",
            "exit 2",
            "",
        ])
    else:
        target_flags = "".join(
            f" --shot {shlex.quote(shot_id)}" for shot_id in target_shots
        )
        shell_lines.extend([
            "uv run "
            f"{shlex.quote(str(_HERE / 'storyboard.py'))} animatic --generate "
            f"--model {shlex.quote(args.model)} --size {shlex.quote(args.size)}"
            f"{target_flags}",
            "",
        ])

    for i, shots in enumerate(groups, 1):
        prefix = shots[0].id if len(shots) == 1 else f"panel-{i:03d}"
        shot_data = [shot.model_dump(mode="json") for shot in shots]
        fingerprints = {
            shot["id"]: contract_fingerprint(shot) for shot in shot_data
        }
        snapshots = {
            shot["id"]: approval_contract(shot) for shot in shot_data
        }
        previous = previous_panels.get(prefix) or {}
        previous_fingerprints = previous.get("contract_fingerprints")
        if not isinstance(previous_fingerprints, dict):
            legacy = previous.get("contract_fingerprint")
            previous_fingerprints = (
                {shots[0].id: legacy}
                if len(shots) == 1 and isinstance(legacy, str)
                else {}
            )
        contract_changed = episode_contract_changed or (
            bool(previous) and previous_fingerprints != fingerprints
        )
        if contract_changed:
            contracts_changed.extend(fingerprints)
        prompt_path = panel_dir / f"{prefix}.prompt.txt"
        prompt = _animatic_panel_prompt(
            ep_dir=ep_dir,
            sb=sb,
            shots=shots,
            panel_no=i,
            panel_count=len(groups),
            lore_front=lore_front,
        )
        prompt_path.write_text(prompt, encoding="utf-8")
        out_images = (
            [] if contract_changed
            else _find_generated_panel_images(panel_dir, prefix)
        )
        panel_item = {
            "id": prefix,
            "shots": [s.id for s in shots],
            "render_style": _animatic_render_style(shots, lore_front),
            "prompt": str(prompt_path),
            "images": [str(p) for p in out_images],
            "reference_images": _animatic_reference_entries(
                ep_dir,
                sb,
                shots,
                render_style=_animatic_render_style(shots, lore_front),
            ),
            "candidates": [],
            "selected_candidate": None,
            "contract_fingerprints": fingerprints,
            "contract_snapshots": snapshots,
        }
        if not contract_changed:
            for key in ("candidates", "selected_candidate", "image_urls", "task_id"):
                if previous.get(key):
                    panel_item[key] = previous[key]
        if not panel_item["candidates"]:
            local_images = [str(path) for path in out_images]
            remote_images = list(previous.get("image_urls", []) or [])
            panel_item["candidates"] = [
                {
                    "id": f"{prefix}-candidate-{candidate_no:02d}",
                    **({"image": local_images[candidate_no - 1]}
                       if candidate_no <= len(local_images) else {}),
                    **({"image_url": remote_images[candidate_no - 1]}
                       if candidate_no <= len(remote_images) else {}),
                }
                for candidate_no in range(1, max(len(local_images), len(remote_images)) + 1)
            ]
        if not panel_item.get("selected_candidate") and panel_item["candidates"]:
            panel_item["selected_candidate"] = panel_item["candidates"][0]["id"]
        manifest["panels"].append(panel_item)

    if contracts_changed:
        manifest["confirmed"] = False
        if confirm_path.exists():
            confirm_path.unlink()
        print(
            "WARN: storyboard approval contract changed for "
            f"{', '.join(sorted(contracts_changed))}; stale candidates were "
            "detached and GATE 2 confirmation was cleared.",
            file=sys.stderr,
        )

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    script_path = panel_dir / "generate-panels.sh"
    script_path.write_text("\n".join(shell_lines).rstrip() + "\n", encoding="utf-8")
    script_path.chmod(0o755)

    if args.generate:
        if openai_image_model:
            print(
                "ERROR: --generate with OpenAI image models is not supported "
                "by the wan-cli helper. Use the emitted prompt files and "
                "panels.json reference_images with the OpenAI image generator.",
                file=sys.stderr,
            )
            return 2
        generation_panels = _targeted_animatic_panels(
            manifest["panels"], target_shots,
        )
        if target_shots:
            print(
                "[animatic] targeting " + ", ".join(target_shots),
                file=sys.stderr,
            )
        for i, item in enumerate(generation_panels, 1):
            prefix = item["id"]
            existing = item.get("candidates", []) or []
            remote_candidates = [
                candidate for candidate in existing
                if isinstance(candidate, dict) and candidate.get("image_url")
            ]
            if len(remote_candidates) != len(existing):
                # A previous interrupted run may have downloaded local files
                # before panels.json was written. Those files are useful for
                # inspection, but using them for video makes wan-cli upload a
                # private OSS URL that omni2video currently rejects with 9006.
                # Keep only candidates whose durable Wan CDN URL survived and
                # regenerate the missing slots.
                item["candidates"] = remote_candidates
                if item.get("selected_candidate") not in {
                    candidate.get("id") for candidate in remote_candidates
                }:
                    item["selected_candidate"] = None
                if confirm_path.exists():
                    confirm_path.unlink()
                existing = remote_candidates
            if not args.force and len(existing) >= args.candidates:
                print(
                    f"[animatic] skip {prefix}: {len(existing)} candidates already exist",
                    file=sys.stderr,
                )
                continue
            if args.force:
                item["candidates"] = []
                item["selected_candidate"] = None
                if confirm_path.exists():
                    confirm_path.unlink()
            while len(item.get("candidates", []) or []) < args.candidates:
                start = len(item.get("candidates", []) or []) + 1
                remaining = args.candidates - start + 1
                print(
                    f"[animatic] generating {prefix} candidates "
                    f"{start}-{args.candidates} ({i}/{len(generation_panels)})",
                    file=sys.stderr,
                )
                try:
                    generated = _generate_wan_panel(
                        item, model=args.model, ratio=args.size,
                        panel_dir=panel_dir, candidate_start=start,
                        max_candidates=remaining,
                    )
                    for offset, (image_path, image_url, task_id) in enumerate(generated):
                        candidate_no = start + offset
                        candidate = {
                            "id": f"{prefix}-candidate-{candidate_no:02d}",
                            "image": str(image_path),
                        }
                        if image_url:
                            candidate["image_url"] = image_url
                        if task_id:
                            candidate["task_id"] = task_id
                        item.setdefault("candidates", []).append(candidate)
                    item["images"] = [
                        candidate["image"]
                        for candidate in item.get("candidates", [])
                        if candidate.get("image")
                    ]
                    item["image_urls"] = [
                        candidate["image_url"]
                        for candidate in item.get("candidates", [])
                        if candidate.get("image_url")
                    ]
                    manifest["confirmed"] = False
                    manifest_path.write_text(
                        json.dumps(manifest, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except (RuntimeError, subprocess.TimeoutExpired) as exc:
                    # Persist every completed candidate before returning so a
                    # later --generate run can resume from its CDN URL instead
                    # of reconstructing a local-only candidate.
                    manifest["confirmed"] = False
                    manifest_path.write_text(
                        json.dumps(manifest, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    print(f"ERROR: image generation failed for {prefix}: {exc}",
                          file=sys.stderr)
                    return 1

            if not item.get("selected_candidate") and item.get("candidates"):
                item["selected_candidate"] = item["candidates"][0]["id"]

        for item in manifest["panels"]:
            item["images"] = [
                candidate["image"] for candidate in item.get("candidates", [])
                if candidate.get("image")
            ]
            item["image_urls"] = [
                candidate["image_url"] for candidate in item.get("candidates", [])
                if candidate.get("image_url")
            ]
        manifest["confirmed"] = confirm_path.exists()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                 encoding="utf-8")

    print(json.dumps({
        "panel_dir": str(panel_dir),
        "manifest": str(manifest_path),
        "generate_script": str(script_path),
        "panels": len(groups),
        "confirmed": confirm_path.exists(),
        "next": (
            "Review generated panel images, then run "
            "`uv run scripts/storyboard.py animatic --confirm` before video render."
        ),
    }, ensure_ascii=False, indent=2))
    return 0


# ------------------------------------------------------------------ estimate

def cmd_estimate(args: argparse.Namespace) -> int:
    ep_dir = _episode_dir()
    sb_path = ep_dir / "storyboard.json"
    sb = Storyboard.model_validate(json.loads(sb_path.read_text()))

    total_sec = sum(int(s.duration) for s in sb.shots)
    n_shots = len(sb.shots)
    groups = compute_chain_groups(sb)
    max_concurrency = int(os.environ.get("SPARK_VIDEO_MAX_CONCURRENCY", "4"))
    group_times = [sum(int(_lookup(sb, sid).duration) for sid in g) for g in groups]
    wall_clock_factor = 1.5  # render_time ≈ 1.5x clip duration (rough)
    est_serial = sum(group_times) * wall_clock_factor
    est_parallel = max(group_times) * wall_clock_factor if groups else 0
    est_with_cap = est_parallel * max(1, len(groups) / max_concurrency)

    long_confirm = int(os.environ.get("SPARK_VIDEO_LONG_CONFIRM_S", "600"))

    provider = sb.provider or os.environ.get("VIDEOGEN_VIDEO_PROVIDER", "wan-cli")
    resolution = sb.resolution

    storyboard_duration_by_kind: dict[str, dict[str, int]] = {}
    for s in sb.shots:
        entry = storyboard_duration_by_kind.setdefault(
            s.kind, {"shots": 0, "seconds": 0}
        )
        entry["shots"] += 1
        entry["seconds"] += int(s.duration)

    # Approved/generated per-shot storyboard panels are uploaded as Wan
    # reference media, which makes the effective provider call r2v even when
    # the director-authored kind is t2v. Cost estimates must describe the call
    # that will actually be submitted, not only the source storyboard shape.
    panel_shot_ids: set[str] = set()
    panel_manifest = ep_dir / "storyboard-panels" / "panels.json"
    if panel_manifest.exists():
        try:
            manifest = json.loads(panel_manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        for item in manifest.get("panels", []) or []:
            shots = item.get("shots") or []
            if len(shots) != 1:
                continue
            has_image = False
            selected_id = item.get("selected_candidate")
            selected = next(
                (
                    candidate for candidate in item.get("candidates", []) or []
                    if isinstance(candidate, dict)
                    and candidate.get("id") == selected_id
                ),
                None,
            )
            candidates = []
            if selected:
                candidates.extend([selected.get("image_url"), selected.get("image")])
            elif not item.get("candidates"):
                candidates.extend(item.get("image_urls", []) or [])
                candidates.extend(item.get("images", []) or [])
            for raw in candidates:
                if not raw:
                    continue
                ref = str(raw)
                if ref.startswith(("http://", "https://", "asset://", "data:")):
                    has_image = True
                    break
                if Path(ref).expanduser().exists():
                    has_image = True
                    break
            if has_image and isinstance(shots[0], str):
                panel_shot_ids.add(shots[0])

    duration_by_kind: dict[str, dict[str, int]] = {}
    for s in sb.shots:
        effective_kind = "r2v" if s.id in panel_shot_ids else s.kind
        entry = duration_by_kind.setdefault(
            effective_kind, {"shots": 0, "seconds": 0}
        )
        entry["shots"] += 1
        entry["seconds"] += int(s.duration)

    out: dict = {
        "shots": n_shots,
        "total_clip_seconds": total_sec,
        "provider": provider,
        "video_model": sb.video_model,
        "resolution": resolution,
        "duration_by_kind": duration_by_kind,
        "storyboard_duration_by_kind": storyboard_duration_by_kind,
        "storyboard_reference_shots": len(panel_shot_ids),
        "parallel_groups": len(groups),
        "estimated_render_seconds_serial": int(est_serial),
        "estimated_render_seconds_parallel": int(est_parallel),
        "estimated_render_seconds_with_concurrency_cap": int(est_with_cap),
        "concurrency_cap": max_concurrency,
        "long_confirm_threshold_s": long_confirm,
    }

    if any(s.speech_source == "post_tts" for s in sb.shots):
        tts_model = os.environ.get("VIDEOGEN_NARRATOR_TTS_MODEL", "cosyvoice-v3-flash")
        tts_chars = sum(
            len(s.speech_text or s.narration_text or "")
            for s in sb.shots
            if s.speech_source == "post_tts"
        )
        out["tts"] = {"model": tts_model, "estimated_chars": tts_chars}

    print(json.dumps(out, ensure_ascii=False, indent=2))

    if total_sec > long_confirm:
        print(f"\nWARN: total clip duration {total_sec}s exceeds "
              f"SPARK_VIDEO_LONG_CONFIRM_S={long_confirm}s — get user confirm.",
              file=sys.stderr)
        return 2
    return 0


def _lookup(sb: Storyboard, shot_id: str) -> Shot:
    for s in sb.shots:
        if s.id == shot_id:
            return s
    raise KeyError(shot_id)


# --------------------------------------------------------------------- graph

def cmd_graph(args: argparse.Namespace) -> int:
    ep_dir = _episode_dir()
    sb_path = ep_dir / "storyboard.json"
    sb = Storyboard.model_validate(json.loads(sb_path.read_text()))
    groups = compute_chain_groups(sb)
    if args.json:
        print(json.dumps(groups, ensure_ascii=False))
    else:
        print(f"# {len(groups)} parallel chain groups, max group size = "
              f"{max(len(g) for g in groups) if groups else 0}")
        for i, g in enumerate(groups, 1):
            print(f"{i:3d}. [{len(g)} shots] {' → '.join(g)}")
    return 0


# ----------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate")
    p_val.add_argument("--scene", type=int, default=None,
                       help="validate one scene fragment instead of full storyboard")
    p_val.set_defaults(fn=cmd_validate)

    p_cmp = sub.add_parser("compile")
    p_cmp.add_argument("--mode", choices=["drama", "narration"], default="drama")
    p_cmp.add_argument("--provider", default=None,
                       help="default: $SPARK_VIDEO_PROVIDER or 'wan-cli'")
    p_cmp.add_argument("--narrator-voice", default=None)
    p_cmp.add_argument(
        "--video-model",
        choices=["wan3.0", "wan2.7"],
        default=os.environ.get("VIDEOGEN_WAN_VIDEO_MODEL", "wan3.0"),
    )
    p_cmp.add_argument(
        "--audio-mode",
        choices=["presenter_voiceover", "native_dialogue", "hybrid"],
        default=None,
        help="explicit episode-wide audio contract; omitted preserves legacy inference",
    )
    p_cmp.add_argument("--presenter", default=None)
    p_cmp.add_argument("--voice", default=None)
    p_cmp.add_argument("--subtitle-mode", choices=["off", "post"], default="off")
    p_cmp.set_defaults(fn=cmd_compile)

    p_anim = sub.add_parser("animatic")
    p_anim.add_argument("--shots-per-image", type=int, choices=[1, 2, 3], default=1,
                        help="deprecated; animatic always generates one image per shot")
    p_anim.add_argument("--model", default="wan2.7-pro",
                        help="image model for --generate")
    p_anim.add_argument("--size", default="16:9",
                        help="image ratio passed to wan image generation")
    p_anim.add_argument("--generate", action="store_true",
                        help="call wan-cli for each clip reference image")
    p_anim.add_argument("--candidates", type=int, choices=range(1, 9), default=4,
                        help="candidate images generated per shot (default: 4)")
    p_anim.add_argument("--force", action="store_true",
                        help="regenerate reference images even if files already exist")
    p_anim.add_argument("--shot", action="append", default=[], metavar="SHOT_ID",
                        help="generate only this shot; repeat for multiple shots")
    p_anim.add_argument("--confirm", action="store_true",
                        help="mark generated reference images approved for video rendering")
    p_anim.add_argument("--select", action="append", metavar="SHOT=CANDIDATE",
                        help="persist a candidate choice; repeat for multiple shots")
    p_anim.add_argument("--unconfirm", action="store_true",
                        help="remove the approval marker")
    p_anim.set_defaults(fn=cmd_animatic)

    p_est = sub.add_parser("estimate")
    p_est.set_defaults(fn=cmd_estimate)

    p_gr = sub.add_parser("graph")
    p_gr.add_argument("--json", action="store_true",
                      help="output JSON array of arrays")
    p_gr.set_defaults(fn=cmd_graph)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
