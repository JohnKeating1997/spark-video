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
import shlex
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from lib.storyboard import Storyboard, Scene, Shot  # noqa: E402
from lib.render_graph import compute_chain_groups   # noqa: E402


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
    warns: list[str] = []

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
    bl = _HERE / "bl"
    if not bl.exists():
        return []

    # Read lore for context
    proj_dir = ep_dir.parent
    lore_path = proj_dir / "lore.md"
    lore_text = lore_path.read_text(encoding="utf-8")[:500] if lore_path.exists() else ""

    # Build per-scene summaries
    scene_blocks = []
    shot_by_scene: dict[str, list] = {}
    for s in sb.shots:
        shot_by_scene.setdefault(s.scene, []).append(s)

    for sc in sb.scenes:
        shots = shot_by_scene.get(sc.id, [])
        if not shots:
            continue
        lines = [f"## Scene {sc.id}: {sc.name} (set: {sc.set_id or 'none'})"]
        for s in shots:
            lines.append(
                f"  {s.id} [{s.kind}, {s.duration}s, chars={s.characters}]: "
                f"{s.prompt[:120]}{'...' if len(s.prompt) > 120 else ''}"
            )
        scene_blocks.append("\n".join(lines))

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
    )
    if lore_text:
        prompt += f"世界设定摘要:\n{lore_text}\n\n"
    prompt += "分镜列表:\n" + "\n\n".join(scene_blocks)

    try:
        proc = subprocess.run(
            [str(bl), "text", "chat", "--model", "qwen-plus",
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
        "scenes": scenes,
        "shots": shots,
        "mode": args.mode,
        "provider": args.provider,
    }
    if args.narrator_voice:
        sb_data["narrator_voice"] = args.narrator_voice

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
            _add_reference_entry(
                refs,
                seen,
                path=cast_index.get(name),
                kind="character",
                name=name,
                instruction=(
                    f"Character reference for {name}. Preserve identity, face "
                    "shape, hairstyle, costume, body type, and apparent age; "
                    "adapt the rendering to the storyboard style. Do not copy "
                    "photorealistic skin texture or live-action realism."
                ),
            )
        set_id = shot.set_id or _scene_set_id(sb, shot.scene)
        if set_id:
            _add_reference_entry(
                refs,
                seen,
                path=set_index.get(set_id),
                kind="location",
                name=set_id,
                instruction=(
                    f"Location reference for {set_id}. Preserve architecture, "
                    "spatial layout, period details, lighting mood, and main "
                    "environmental elements; adapt to the storyboard style."
                ),
            )
        for name in shot.props or []:
            _add_reference_entry(
                refs,
                seen,
                path=prop_index.get(name),
                kind="prop",
                name=name,
                instruction=(
                    f"Prop reference for {name}. Preserve shape, material, "
                    "color, texture, and scale; adapt to the storyboard style "
                    "and do not override the shot action."
                ),
            )
    return refs

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

def _tc(seconds: int) -> str:
    m, s = divmod(max(0, int(seconds)), 60)
    return f"{m:02d}:{s:02d}"


def _shot_offsets(sb: Storyboard) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    t = 0
    for shot in sb.shots:
        start = t
        t += int(shot.duration)
        out[shot.id] = (start, t)
    return out


def _chunks(seq: list[Shot], n: int) -> list[list[Shot]]:
    return [seq[i:i + n] for i in range(0, len(seq), n)]


def _animatic_panel_prompt(
    *,
    ep_dir: Path,
    sb: Storyboard,
    shots: list[Shot],
    panel_no: int,
    panel_count: int,
    offsets: dict[str, tuple[int, int]],
    lore_front: dict[str, str | list[str]],
) -> str:
    visual_style = str(lore_front.get("visual_style") or "").strip()
    mood_anchor = str(lore_front.get("mood_anchor") or "").strip()
    camera = str(lore_front.get("camera_language") or "").strip()
    palette_raw = lore_front.get("palette") or []
    palette = ", ".join(palette_raw) if isinstance(palette_raw, list) else str(palette_raw)

    style_bits = [
        "static storyboard reference image",
        "cinematic blocking",
        "clear composition",
        "consistent characters, locations, and props",
    ]
    if visual_style:
        style_bits.append(visual_style)
    if camera:
        style_bits.append(camera)
    if palette:
        style_bits.append(f"palette: {palette}")
    if mood_anchor:
        style_bits.append(mood_anchor)

    lines = [
        f"Create static storyboard reference image {panel_no}/{panel_count} "
        f"for one video clip.",
        "",
        "Style: " + "; ".join(style_bits) + ".",
        "Layout: one still image for exactly one clip, readable composition, no speech bubbles, no subtitles, no UI, no panel labels.",
        "Purpose: static previsualization for user approval before paid video rendering.",
        "",
        "Clip:",
    ]
    reference_entries = _animatic_reference_entries(ep_dir, sb, shots)
    if reference_entries:
        lines.extend([
            "",
            "Reference image map:",
        ])
        for idx, ref in enumerate(reference_entries, 1):
            lines.append(f"Image {idx}: {ref['instruction']}")
        lines.extend([
            "The image numbers must exactly match the uploaded reference image order. Use each image only for its assigned role. These images are references for the static storyboard composition and continuity; do not copy labels, borders, captions, UI, photorealistic skin texture, or live-action camera realism.",
            "",
            "When generating the still storyboard, follow the reference images for identity, location, and prop continuity while prioritizing this clip's composition, action, mood, and declared visual style.",
            "",
        ])
    for idx, shot in enumerate(shots, 1):
        start, end = offsets[shot.id]
        panel_prompt = (shot.animatic_prompt or shot.prompt).strip()
        panel_prompt = " ".join(panel_prompt.split())
        chars = ", ".join(shot.characters or []) or "none"
        lines.extend([
            f"{idx}. {shot.id} [{_tc(start)}-{_tc(end)}], {shot.kind}, {shot.duration}s",
            f"   Characters: {chars}",
            f"   Visual: {panel_prompt}",
            f"   Narrative purpose: {shot.narrative_purpose or 'n/a'}",
        ])
    lines.extend([
        "",
        "Important: this is a still storyboard reference for one video clip, "
        "not a finished illustration and not a video first frame. Keep it clear "
        "enough to judge framing, action, mood, and continuity.",
    ])
    return "\n".join(lines).strip() + "\n"


def _find_generated_panel_images(panel_dir: Path, prefix: str) -> list[Path]:
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    exact_stems = {prefix, f"{prefix}-openai"}
    return sorted(
        p for p in panel_dir.glob(f"{prefix}*")
        if (
            p.is_file()
            and p.suffix.lower() in exts
            and p.stem in exact_stems
        )
    )


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

    if args.confirm:
        manifest_path = panel_dir / "panels.json"
        if not manifest_path.exists():
            print(
                f"ERROR: {manifest_path} missing. Run "
                "`uv run scripts/storyboard.py animatic` first.",
                file=sys.stderr,
            )
            return 2
        confirm_path.write_text(
            "User approved per-shot static storyboard reference images for video rendering.\n",
            encoding="utf-8",
        )
        print(f"confirmed {panel_dir}")
        return 0

    if args.unconfirm:
        if confirm_path.exists():
            confirm_path.unlink()
        print(f"removed confirmation marker: {confirm_path}")
        return 0

    sb = Storyboard.model_validate(json.loads(sb_path.read_text(encoding="utf-8")))
    lore_front = _read_lore_front(ep_dir)
    offsets = _shot_offsets(sb)
    if args.shots_per_image != 1:
        print(
            "WARN: --shots-per-image is deprecated; animatic now always "
            "generates one static storyboard reference image per clip.",
            file=sys.stderr,
        )
    groups = _chunks(sb.shots, 1)

    manifest: dict = {
        "storyboard": str(sb_path),
        "shots_per_image": 1,
        "mode": "per_shot_reference_image",
        "model": args.model,
        "size": args.size,
        "panels": [],
        "confirmed": confirm_path.exists(),
    }

    shell_lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f"cd {shlex.quote(str(_HERE.parent))}",
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
            "echo 'The BL image helper is intentionally disabled for this animatic run.'",
            "exit 2",
            "",
        ])

    for i, shots in enumerate(groups, 1):
        prefix = shots[0].id if len(shots) == 1 else f"panel-{i:03d}"
        prompt_path = panel_dir / f"{prefix}.prompt.txt"
        prompt = _animatic_panel_prompt(
            ep_dir=ep_dir,
            sb=sb,
            shots=shots,
            panel_no=i,
            panel_count=len(groups),
            offsets=offsets,
            lore_front=lore_front,
        )
        prompt_path.write_text(prompt, encoding="utf-8")
        out_images = _find_generated_panel_images(panel_dir, prefix)
        manifest["panels"].append({
            "id": prefix,
            "shots": [s.id for s in shots],
            "prompt": str(prompt_path),
            "images": [str(p) for p in out_images],
            "reference_images": _animatic_reference_entries(ep_dir, sb, shots),
        })
        if not openai_image_model:
            shell_lines.extend([
                f"echo '[animatic] {prefix}: {' '.join(s.id for s in shots)}'",
                "./scripts/bl image generate "
                f"--model {shlex.quote(args.model)} "
                f"--prompt \"$(cat {shlex.quote(str(prompt_path))})\" "
                f"--size {shlex.quote(args.size)} "
                f"--out-dir {shlex.quote(str(panel_dir))} "
                f"--out-prefix {shlex.quote(prefix)}",
                "",
            ])

    manifest_path = panel_dir / "panels.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    script_path = panel_dir / "generate-panels.sh"
    script_path.write_text("\n".join(shell_lines).rstrip() + "\n", encoding="utf-8")
    script_path.chmod(0o755)

    if args.generate:
        if openai_image_model:
            print(
                "ERROR: --generate with OpenAI image models is not supported "
                "by the BL helper. Use the emitted prompt files and "
                "panels.json reference_images with the OpenAI image generator.",
                file=sys.stderr,
            )
            return 2
        env = os.environ.copy()
        env["SPARK_VIDEO_PHASE"] = "animatic"
        for i, item in enumerate(manifest["panels"], 1):
            prefix = item["id"]
            if not args.force and _find_generated_panel_images(panel_dir, prefix):
                print(f"[animatic] skip {prefix}: image already exists", file=sys.stderr)
                continue
            prompt_text = Path(item["prompt"]).read_text(encoding="utf-8")
            cmd = [
                str(_HERE / "bl"), "image", "generate",
                "--model", args.model,
                "--prompt", prompt_text,
                "--size", args.size,
                "--out-dir", str(panel_dir),
                "--out-prefix", prefix,
            ]
            print(f"[animatic] generating {prefix} ({i}/{len(manifest['panels'])})",
                  file=sys.stderr)
            proc = subprocess.run(cmd, text=True, env=env, cwd=str(_HERE.parent))
            if proc.returncode != 0:
                print(f"ERROR: image generation failed for {prefix}", file=sys.stderr)
                return proc.returncode

        for item in manifest["panels"]:
            item["images"] = [
                str(p) for p in _find_generated_panel_images(panel_dir, item["id"])
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

    provider = sb.provider or os.environ.get("VIDEOGEN_VIDEO_PROVIDER", "bl")
    resolution = sb.resolution

    duration_by_kind: dict[str, dict[str, int]] = {}
    for s in sb.shots:
        entry = duration_by_kind.setdefault(s.kind, {"shots": 0, "seconds": 0})
        entry["shots"] += 1
        entry["seconds"] += int(s.duration)

    out: dict = {
        "shots": n_shots,
        "total_clip_seconds": total_sec,
        "provider": provider,
        "resolution": resolution,
        "duration_by_kind": duration_by_kind,
        "parallel_groups": len(groups),
        "estimated_render_seconds_serial": int(est_serial),
        "estimated_render_seconds_parallel": int(est_parallel),
        "estimated_render_seconds_with_concurrency_cap": int(est_with_cap),
        "concurrency_cap": max_concurrency,
        "long_confirm_threshold_s": long_confirm,
    }

    if sb.mode == "narration":
        tts_model = os.environ.get("VIDEOGEN_NARRATOR_TTS_MODEL", "cosyvoice-v3-flash")
        tts_chars = sum(
            len(s.narration_text or "")
            for s in sb.shots
            if s.role == "narration"
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
                       help="default: $SPARK_VIDEO_PROVIDER or 'bl'")
    p_cmp.add_argument("--narrator-voice", default=None)
    p_cmp.set_defaults(fn=cmd_compile)

    p_anim = sub.add_parser("animatic")
    p_anim.add_argument("--shots-per-image", type=int, choices=[1, 2, 3], default=1,
                        help="deprecated; animatic always generates one image per shot")
    p_anim.add_argument("--model", default="wan2.6-t2i",
                        help="image model for --generate")
    p_anim.add_argument("--size", default="16:9",
                        help="image aspect ratio / size passed to bl image generate")
    p_anim.add_argument("--generate", action="store_true",
                        help="call ./scripts/bl image generate for each clip reference image")
    p_anim.add_argument("--force", action="store_true",
                        help="regenerate reference images even if files already exist")
    p_anim.add_argument("--confirm", action="store_true",
                        help="mark generated reference images approved for video rendering")
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
