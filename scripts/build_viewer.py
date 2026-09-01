# /// script
# requires-python = ">=3.10"
# dependencies = ["pydantic>=2.5", "PyYAML>=6.0"]
# ///
"""
build_viewer.py — emit a self-contained viewer.html for one episode.

Walks <project>/ and <episode>/ artifacts and renders a single HTML page
that shows premise, lore, direction, script, cast/sets/props, every shot
(with its static storyboard reference, all clip versions + review scores,
winner highlighted), and the final stitched mp4. All media is referenced
via relative paths — no files are copied.

Run:
    SPARK_VIDEO_PROJECT=foo SPARK_VIDEO_EPISODE=001 \\
        uv run scripts/build_viewer.py [--no-open]

The page auto-opens on macOS unless --no-open is passed.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import platform
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from lib.env import load_pwd_dotenv  # noqa: E402
from lib.cli import active_wan_site  # noqa: E402
from lib.prompt_language import (  # noqa: E402
    read_project_prompt_language,
)
from lib.cinematic import cinematic_budget  # noqa: E402
from lib.state import episode_dir, project_dir, normalize_episode_id  # noqa: E402

load_pwd_dotenv()


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a"}
VIDEO_EXTS = {".mp4", ".mov", ".webm"}
_SENSITIVE_KEY = re.compile(
    r"(?:access[_-]?key|authorization|cookie|credential|secret|signature|token)",
    re.IGNORECASE,
)
_HTTP_URL = re.compile(r"https?://[^\s\"'<>]+")


# ---------- helpers ---------------------------------------------------------


def _resolve_ids() -> tuple[str, str]:
    proj = os.environ.get("SPARK_VIDEO_PROJECT", "")
    ep = os.environ.get("SPARK_VIDEO_EPISODE", "")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default=proj or None)
    ap.add_argument("--episode", default=ep or None)
    ap.add_argument("--no-open", action="store_true")
    args, _rest = ap.parse_known_args()
    if not args.project or not args.episode:
        print("ERROR: --project/--episode or SPARK_VIDEO_PROJECT/SPARK_VIDEO_EPISODE required",
              file=sys.stderr)
        sys.exit(2)
    return args.project, args.episode, args.no_open


def _rel(target: Path, base: Path) -> str:
    """Relative URL path from base file (not its dir) to target. URL-encoded."""
    try:
        rel = os.path.relpath(target, base)
    except ValueError:
        rel = str(target)
    return urllib.parse.quote(rel.replace(os.sep, "/"), safe="/")


def _read_text(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _rewrite_premise_image_paths(text: str, premise_path: Path, ep_dir: Path) -> str:
    """Make local Markdown images in Premise resolve from viewer.html."""
    pattern = re.compile(r"(!\[[^\]]*\]\()(<[^>]+>|[^)\s]+)(\))")

    def replace(match: re.Match[str]) -> str:
        raw = match.group(2)
        target = raw[1:-1] if raw.startswith("<") and raw.endswith(">") else raw
        if target.startswith(("http://", "https://", "data:", "asset://")):
            return match.group(0)
        decoded = urllib.parse.unquote(target)
        path = Path(decoded).expanduser()
        if not path.is_absolute():
            path = premise_path.parent / path
        try:
            path = path.resolve()
        except OSError:
            return match.group(0)
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
            return match.group(0)
        return f"{match.group(1)}{_rel(path, ep_dir)}{match.group(3)}"

    return pattern.sub(replace, text)


def _load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _redact_url_queries(text: str) -> str:
    """Remove query strings and fragments from URLs embedded in log text."""
    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        trailing = ""
        while raw and raw[-1] in "),.;]}":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        parsed = urllib.parse.urlsplit(raw)
        clean = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, "", "")
        )
        if parsed.query or parsed.fragment:
            clean += "?<redacted>"
        return clean + trailing

    return _HTTP_URL.sub(replace, text)


def _sanitize_for_viewer(value, *, key: str = ""):
    """Redact secrets and signed URL queries from Viewer-only log copies."""
    if _SENSITIVE_KEY.search(key):
        return "<redacted>"
    if isinstance(value, dict):
        return {
            str(child_key): _sanitize_for_viewer(child, key=str(child_key))
            for child_key, child in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_for_viewer(child) for child in value]
    if isinstance(value, str):
        return _redact_url_queries(value)
    return value


def _sorted_dir(p: Path) -> list[Path]:
    try:
        return sorted(p.iterdir(), key=lambda x: x.name)
    except FileNotFoundError:
        return []


def _strip_frontmatter(md: str) -> tuple[dict, str]:
    """Extract YAML front matter while preserving a readable Markdown body."""
    fm: dict = {}
    body = md
    if md.startswith("---"):
        end = md.find("\n---", 3)
        if end > 0:
            block = md[3:end].strip()
            body = md[end + 4:].lstrip("\n")
            try:
                parsed = yaml.safe_load(block)
                if isinstance(parsed, dict):
                    fm = parsed
            except yaml.YAMLError:
                fm = {}
    return fm, body


# ---------- collectors ------------------------------------------------------


def _collect_assets(root: Path, ep_dir: Path) -> dict[str, list[str]]:
    """Group asset URLs (relative to viewer.html) by type for one folder."""
    images, audios, videos, others = [], [], [], []
    for f in _sorted_dir(root):
        if not f.is_file():
            continue
        if f.name.startswith("."):
            continue
        url = _rel(f, ep_dir)
        ext = f.suffix.lower()
        if ext in IMAGE_EXTS:
            images.append(url)
        elif ext in AUDIO_EXTS:
            audios.append(url)
        elif ext in VIDEO_EXTS:
            videos.append(url)
        elif f.name not in ("cast.md", "set.md", "prop.md"):
            others.append(url)
    return {"images": images, "audios": audios, "videos": videos, "others": others}


def _manifest_entries(data: object) -> dict[str, dict]:
    """Normalize flat and legacy nested asset manifests."""
    if not isinstance(data, dict):
        return {}
    for key in ("characters", "sets", "props"):
        nested = data.get(key)
        if isinstance(nested, dict):
            return {
                str(name): value
                for name, value in nested.items()
                if isinstance(value, dict)
            }
        if isinstance(nested, list):
            return {
                str(value.get("name")): value
                for value in nested
                if isinstance(value, dict) and value.get("name")
            }
    return {
        str(name): value
        for name, value in data.items()
        if isinstance(value, dict)
    }


def _selected_entity_image(entry: dict | None, asset_dir: Path) -> Path | None:
    if not entry:
        return None
    values = []
    if isinstance(entry.get("selected_image"), str):
        values.append(entry["selected_image"])
    values.extend(
        value for value in entry.get("images", []) if isinstance(value, str)
    )
    for value in values:
        path = Path(value).expanduser()
        path = (Path.cwd() / path).resolve() if not path.is_absolute() else path.resolve()
        try:
            path.relative_to(asset_dir.resolve())
        except ValueError:
            continue
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            return path
    return None


def _recommended_entity_image(asset_dir: Path) -> Path | None:
    recommendation_path = asset_dir / ".asset-recommendation.json"
    try:
        recommendation = json.loads(recommendation_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    filename = (
        recommendation.get("recommended_image")
        if isinstance(recommendation, dict)
        else None
    )
    if not isinstance(filename, str) or Path(filename).name != filename:
        return None
    image = asset_dir / filename
    if image.is_file() and image.suffix.lower() in IMAGE_EXTS:
        return image
    return None


def _collect_entities(
    parent: Path,
    ep_dir: Path,
    md_name: str,
    manifest_entries: dict[str, dict] | None = None,
) -> list[dict]:
    """Walk <parent>/<name>/ folders and emit cast/set/prop entries."""
    out = []
    if not parent.exists():
        return out
    for d in _sorted_dir(parent):
        if not d.is_dir():
            continue
        md = _read_text(d / md_name) or ""
        fm, body = _strip_frontmatter(md)
        assets = _collect_assets(d, ep_dir)
        selected = _selected_entity_image((manifest_entries or {}).get(d.name), d)
        selected_url = _rel(selected, ep_dir) if selected else None
        recommended = _recommended_entity_image(d)
        recommended_url = _rel(recommended, ep_dir) if recommended else None
        if selected_url and selected_url in assets["images"]:
            assets["images"] = [selected_url] + [
                image for image in assets["images"] if image != selected_url
            ]
        out.append({
            "name": d.name,
            "frontmatter": fm,
            "body": body,
            "selected_image": selected_url,
            "recommended_image": recommended_url,
            **assets,
        })
    return out


def _path_source(path: Path, proj_dir: Path) -> str:
    try:
        return str(path.relative_to(proj_dir.parent))
    except ValueError:
        return str(path)


def _collect_entity_group(
    *,
    scope: str,
    label: str,
    parent: Path,
    ep_dir: Path,
    proj_dir: Path,
    md_name: str,
    manifest_path: Path,
    manifest_entries: dict[str, dict] | None = None,
) -> dict | None:
    """Collect one source tier for cast/set/prop assets."""
    entities = _collect_entities(parent, ep_dir, md_name, manifest_entries)
    has_folder = parent.exists()
    has_manifest = manifest_path.exists()
    if not entities and not has_folder and not has_manifest:
        return None
    for entity in entities:
        entity["scope"] = scope
        entity["source_root"] = _path_source(parent, proj_dir)
    return {
        "scope": scope,
        "label": label,
        "source_root": _path_source(parent, proj_dir),
        "source_url": _rel(parent, ep_dir) if has_folder else None,
        "manifest": _path_source(manifest_path, proj_dir) if has_manifest else None,
        "manifest_url": _rel(manifest_path, ep_dir) if has_manifest else None,
        "entities": entities,
    }


def _collect_entity_groups(
    *,
    proj_dir: Path,
    ep_dir: Path,
    folder_name: str,
    md_name: str,
    manifest_name: str,
) -> list[dict]:
    """Return episode-local assets first, then project-global assets."""
    groups = []
    # The episode manifest is the merged source of truth for both tiers.
    # Folder validation prevents a same-name override selecting across tiers.
    entries = _manifest_entries(_load_json(ep_dir / manifest_name))
    for scope, label, root in [
        ("episode", "Episode local", ep_dir),
        ("global", "Project global", proj_dir),
    ]:
        group = _collect_entity_group(
            scope=scope,
            label=label,
            parent=root / folder_name,
            ep_dir=ep_dir,
            proj_dir=proj_dir,
            md_name=md_name,
            manifest_path=root / manifest_name,
            manifest_entries=entries,
        )
        if group:
            groups.append(group)
    return groups


def _flatten_entity_groups(groups: list[dict]) -> list[dict]:
    out: list[dict] = []
    for group in groups:
        out.extend(group.get("entities", []))
    return out


def _collect_lore_sections(proj_dir: Path, ep_dir: Path) -> list[dict]:
    sections = []
    for scope, label, path in [
        ("episode", "Episode override", ep_dir / "lore.md"),
        ("global", "Project story bible", proj_dir / "lore.md"),
    ]:
        body = _read_text(path)
        if not body or not body.strip():
            continue
        frontmatter, content = _strip_frontmatter(body)
        sections.append({
            "scope": scope,
            "label": label,
            "source": _path_source(path, proj_dir),
            "url": _rel(path, ep_dir),
            "frontmatter": frontmatter,
            "body": content,
        })
    return sections


def _collect_scenes(ep_dir: Path) -> list[dict]:
    out = []
    scenes_dir = ep_dir / "scenes"
    if not scenes_dir.exists():
        return out
    md_files = sorted(scenes_dir.glob("scene-*.md"))
    for md in md_files:
        body = _read_text(md) or ""
        js = _load_json(scenes_dir / md.with_suffix(".json").name)
        out.append({"name": md.stem, "body": body, "json": js})
    return out


def _collect_storyboard_panels(ep_dir: Path) -> dict[str, dict]:
    """Index storyboard candidate panels and the selected reference per shot."""
    panel_dir = ep_dir / "storyboard-panels"
    manifest_path = panel_dir / "panels.json"
    manifest = _load_json(manifest_path) or {}
    confirmed = bool(manifest.get("confirmed") or (panel_dir / "CONFIRMED").exists())
    out: dict[str, dict] = {}

    def local_file(value: str) -> Path | None:
        path = Path(value).expanduser()
        candidates = [path]
        if not path.is_absolute():
            candidates.extend([panel_dir / path, ep_dir / path])
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved.is_file():
                return resolved
        return None

    for item in manifest.get("panels", []) or []:
        if not isinstance(item, dict):
            continue
        shots = item.get("shots") or []
        if len(shots) != 1 or not isinstance(shots[0], str):
            continue
        shot_id = shots[0]
        candidate_items = item.get("candidates", []) or []
        if not candidate_items:
            local_images = list(item.get("images", []) or [])
            remote_images = list(item.get("image_urls", []) or [])
            candidate_items = [
                {
                    "id": f"{item.get('id', shot_id)}-candidate-{index + 1:02d}",
                    **({"image": local_images[index]} if index < len(local_images) else {}),
                    **({"image_url": remote_images[index]} if index < len(remote_images) else {}),
                    **({"task_id": item.get("task_id")} if index == 0 and item.get("task_id") else {}),
                }
                for index in range(max(len(local_images), len(remote_images)))
            ]

        candidates = []
        for index, candidate in enumerate(candidate_items, 1):
            if not isinstance(candidate, dict):
                continue
            display_url = None
            source = None
            local_value = candidate.get("image")
            if local_value:
                image_path = local_file(str(local_value))
                if image_path:
                    display_url = _rel(image_path, ep_dir)
                    try:
                        source = str(image_path.relative_to(ep_dir))
                    except ValueError:
                        source = str(image_path)
            remote_value = candidate.get("image_url")
            if not display_url and isinstance(remote_value, str) and remote_value.startswith(
                ("http://", "https://", "data:")
            ):
                display_url = remote_value
                source = "storyboard-panels/panels.json"
            candidates.append({
                "id": candidate.get("id") or f"{shot_id}-candidate-{index:02d}",
                "image_url": display_url,
                "source": source,
                "task_id": candidate.get("task_id"),
            })

        selected_candidate = item.get("selected_candidate")
        if not selected_candidate and candidates:
            selected_candidate = candidates[0]["id"]
        selected = next(
            (candidate for candidate in candidates if candidate["id"] == selected_candidate),
            None,
        )

        prompt_text = None
        prompt_value = item.get("prompt")
        if isinstance(prompt_value, str):
            prompt_path = local_file(prompt_value)
            if prompt_path:
                prompt_text = _read_text(prompt_path)

        out[shot_id] = {
            "image_url": selected.get("image_url") if selected else None,
            "source": selected.get("source") if selected else None,
            "prompt": prompt_text,
            "confirmed": confirmed and selected is not None,
            "task_id": selected.get("task_id") if selected else None,
            "candidates": candidates,
            "selected_candidate": selected_candidate,
        }
    return out


def _collect_shots(
    ep_dir: Path,
    storyboard: dict | None,
    sent_by_shot_ver: dict[str, str] | None = None,
    execution_by_shot_ver: dict[str, dict] | None = None,
    storyboard_panels: dict[str, dict] | None = None,
) -> list[dict]:
    """For each shot in storyboard order, find all clip versions on disk."""
    state = _load_json(ep_dir / "shots_state.json") or {}
    clips_dir = ep_dir / "clips"
    frames_dir = ep_dir / "frames"
    reviews_dir = ep_dir / "reviews"
    sent_by_shot_ver = sent_by_shot_ver or {}
    execution_by_shot_ver = execution_by_shot_ver or {}
    storyboard_panels = storyboard_panels or {}
    storyboard_provider = storyboard.get("provider") if storyboard else None

    shot_specs: list[dict] = []
    if storyboard:
        for sc in storyboard.get("scenes", []):
            for sh in sc.get("shots", []) if isinstance(sc.get("shots"), list) else []:
                shot_specs.append(sh)
        # Some storyboards keep shots at top level instead
        if not shot_specs and isinstance(storyboard.get("shots"), list):
            shot_specs = storyboard["shots"]

    # Fallback: derive from state keys if storyboard absent
    if not shot_specs:
        shot_specs = [{"id": sid} for sid in sorted(state.keys())]

    ver_re = re.compile(r"^(?P<id>.+)-ver(?P<n>\d+)\.mp4$")

    out = []
    for spec in shot_specs:
        sid = spec.get("id") or spec.get("shot_id")
        if not sid:
            continue
        entry = state.get(sid) or {}
        winner = entry.get("winner_version")

        # discover versions on disk (truth) — don't trust state paths
        versions = []
        if clips_dir.exists():
            for clip in sorted(clips_dir.glob(f"{sid}-ver*.mp4")):
                m = ver_re.match(clip.name)
                if not m:
                    continue
                n = int(m.group("n"))
                attempt = next(
                    (
                        a for a in entry.get("attempts", [])
                        if a.get("version", a.get("target_version")) == n
                    ),
                    {},
                )
                execution = execution_by_shot_ver.get(f"{sid}::{n}") or {}
                review = attempt.get("review")
                if not review:
                    review = _load_json(reviews_dir / f"{sid}-ver{n}.json")
                thumb = frames_dir / f"{sid}-ver{n}_last.png"
                recorded_prompt = attempt.get("prompt")
                sent_prompt = sent_by_shot_ver.get(f"{sid}::{n}")
                model = attempt.get("model") or execution.get("model")
                kind = attempt.get("kind") or execution.get("kind") or spec.get("kind")
                command = attempt.get("command") or execution.get("command")
                if not command and model == "wan3.0":
                    command = "omni2video"
                elif not command and model == "wan2.7":
                    command = {
                        "t2v": "text2video",
                        "i2v": "frame2video",
                        "r2v": "reference2video",
                    }.get(kind)
                versions.append({
                    "version": n,
                    "clip_url": _rel(clip, ep_dir),
                    "thumb_url": _rel(thumb, ep_dir) if thumb.exists() else None,
                    "prompt": recorded_prompt,
                    "sent_prompt": sent_prompt,
                    "review": review,
                    "status": attempt.get("status"),
                    "task_id": attempt.get("task_id") or execution.get("task_id"),
                    "provider": attempt.get("provider") or execution.get("provider"),
                    "kind": kind,
                    "model": model,
                    "command": command,
                })

        out.append({
            "id": sid,
            "scene": spec.get("scene"),
            "narrative_purpose": spec.get("narrative_purpose"),
            "duration": spec.get("duration"),
            "cinematic_budget": cinematic_budget(int(spec.get("duration") or 12)),
            "kind": spec.get("kind"),
            "provider": spec.get("provider") or storyboard_provider,
            "characters": spec.get("characters", []),
            "prompt": spec.get("prompt"),
            "camera_path": spec.get("camera_path"),
            "end_composition": spec.get("end_composition"),
            "animatic_prompt": spec.get("animatic_prompt"),
            "speech_source": spec.get("speech_source"),
            "speaker": spec.get("speaker"),
            "speech_text": spec.get("speech_text") or spec.get("narration_text"),
            "visual_speech_mode": spec.get("visual_speech_mode"),
            "allow_generated_text": spec.get("allow_generated_text", False),
            "long_take_reason": spec.get("long_take_reason"),
            "beats": spec.get("beats", []),
            "props": spec.get("props", []),
            "set_id": spec.get("set_id"),
            "transition_from_previous": spec.get("transition_from_previous"),
            "use_prev_last_frame_as_first": spec.get(
                "use_prev_last_frame_as_first", False
            ),
            "storyboard_panel": storyboard_panels.get(sid),
            "winner_version": winner,
            "versions": versions,
        })
    return out


def _extract_sent_prompt(rec: dict) -> str | None:
    """Recover the literal prompt that hit the model from one log record.

    Handles two logger schemas:
      * lib/model_log.py — ``request`` is a dict that contains ``input.prompt``
        (DashScope shape) or ``parameters.prompt`` on some endpoints.
      * scripts/bl wrapper — records have a ``cmd`` array; we grep it for
        the value following ``--prompt``.
    Returns None when no prompt is identifiable (e.g. wait / review calls).
    """
    req = rec.get("request")
    if isinstance(req, dict):
        inp = req.get("input")
        if isinstance(inp, dict) and isinstance(inp.get("prompt"), str):
            return inp["prompt"]
        params = req.get("parameters")
        if isinstance(params, dict) and isinstance(params.get("prompt"), str):
            return params["prompt"]
        if isinstance(req.get("prompt"), str):
            return req["prompt"]
    cmd = rec.get("cmd")
    if not isinstance(cmd, list) and isinstance(req, dict):
        cmd = req.get("cmd")
    if isinstance(cmd, list):
        for i, tok in enumerate(cmd):
            if tok == "--prompt" and i + 1 < len(cmd):
                return cmd[i + 1]
    return None


def _is_video_render_record(rec: dict) -> bool:
    """Best-effort: does this log record correspond to a video render submit?"""
    k = (rec.get("kind") or "").lower()
    if k in {"video_generate", "video_submit", "video_render", "video"}:
        return True
    cmd = rec.get("cmd")
    if not isinstance(cmd, list) and isinstance(rec.get("request"), dict):
        cmd = rec["request"].get("cmd")
    if isinstance(cmd, list) and any(
        token in cmd
        for token in (
            "omni2video",
            "text2video",
            "frame2video",
            "reference2video",
        )
    ):
        return True
    if isinstance(cmd, list) and len(cmd) >= 3 and cmd[0] == "bl" and cmd[1] == "video":
        return cmd[2] in {"generate", "ref", "edit"}
    return False


def _collect_calls(ep_dir: Path) -> dict:
    """Group model_calls.jsonl by shot; return summary + raw + sent-prompt index.

    Two logger schemas coexist in the repo (see lib/model_log.py docstring
    and scripts/bl). Field names differ:
      * Python logger: shot_id / version / duration_ms / kind
      * Shell wrapper: shot   / attempt / duration_ms / (no kind, infer from cmd)
    We accept both so the calls table populates per-shot in either case, and
    we also harvest the actual ``--prompt`` value sent to the video model so
    the shots section can show it as ground truth.
    """
    log = ep_dir / "logs" / "model_calls.jsonl"
    by_shot: dict = {}
    raw: list = []
    sent_by_shot_ver: dict[str, str] = {}
    execution_by_shot_ver: dict[str, dict] = {}
    total = 0
    if not log.exists():
        return {
            "by_shot": by_shot, "total": 0, "raw_count": 0,
            "raw": [], "sent_by_shot_ver": sent_by_shot_ver,
            "execution_by_shot_ver": execution_by_shot_ver,
        }
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        total += 1
        raw.append(_sanitize_for_viewer(rec))
        sid = rec.get("shot_id") or rec.get("shot") or "_project_"
        slot = by_shot.setdefault(sid, {"count": 0, "duration_ms": 0.0, "kinds": {}})
        slot["count"] += 1
        d = rec.get("duration_ms") or 0
        try:
            slot["duration_ms"] += float(d)
        except (TypeError, ValueError):
            pass
        k = rec.get("kind")
        if not k:
            cmd = rec.get("cmd")
            if isinstance(cmd, list) and len(cmd) >= 3 and cmd[0] == "bl":
                k = f"bl_{cmd[1]}_{cmd[2]}"
            else:
                k = "?"
        slot["kinds"][k] = slot["kinds"].get(k, 0) + 1

        if _is_video_render_record(rec):
            prompt = _extract_sent_prompt(rec)
            ver = rec.get("version") or rec.get("attempt")
            if ver is not None:
                key = f"{sid}::{ver}"
                if prompt:
                    # Keep the first occurrence per (shot, version). render_shot
                    # passes the prompt only once per attempt so collisions are
                    # rare and the first call is the truthful one.
                    sent_by_shot_ver.setdefault(key, prompt)
                request = rec.get("request") if isinstance(rec.get("request"), dict) else {}
                cmd = request.get("cmd") if isinstance(request.get("cmd"), list) else rec.get("cmd")
                command = next((token for token in (cmd or []) if token in {
                    "omni2video", "text2video", "frame2video",
                    "image2video", "reference2video", "videoedit",
                }), None)
                model = rec.get("model")
                if not model and isinstance(cmd, list) and "--model" in cmd:
                    model_index = cmd.index("--model")
                    if model_index + 1 < len(cmd):
                        model = cmd[model_index + 1]
                candidate = {
                    "provider": rec.get("provider"),
                    "model": model,
                    "kind": request.get("kind"),
                    "command": command,
                    "task_id": rec.get("task_id"),
                    "_succeeded": not rec.get("error") and bool(
                        rec.get("task_id") or rec.get("response")
                    ),
                }
                current = execution_by_shot_ver.get(key)
                if current is None or candidate["_succeeded"] or not current.get("_succeeded"):
                    execution_by_shot_ver[key] = candidate
    return {
        "by_shot": by_shot, "total": total, "raw_count": len(raw),
        "raw": raw, "sent_by_shot_ver": sent_by_shot_ver,
        "execution_by_shot_ver": execution_by_shot_ver,
    }


def _collect_final(ep_dir: Path, project: str, episode_norm: str) -> dict | None:
    final_dir = ep_dir / "final"
    if not final_dir.exists():
        return None
    # primary expected name
    cands = list(final_dir.glob("*.mp4"))
    if not cands:
        return None
    # prefer "<project>-<episode>.mp4"
    expected = f"{project}-{episode_norm}.mp4"
    chosen = next((c for c in cands if c.name == expected), cands[0])
    return {
        "name": chosen.name,
        "url": _rel(chosen, ep_dir),
        "size_bytes": chosen.stat().st_size,
    }


def _collect_bgm(proj_dir: Path, ep_dir: Path) -> list[dict]:
    bgm_dir = proj_dir / "bgm"
    out = []
    if not bgm_dir.exists():
        return out
    for f in _sorted_dir(bgm_dir):
        if f.suffix.lower() in AUDIO_EXTS:
            out.append({"name": f.name, "url": _rel(f, ep_dir)})
    return out


# ---------- HTML emission ---------------------------------------------------


_MARKED_JS = (_HERE.parent / "lib" / "vendor" / "marked.min.js").read_text(encoding="utf-8")
_VIEWER_DIR = _HERE / "viewer"
_VIEWER_TEMPLATE = (_VIEWER_DIR / "template.html").read_text(encoding="utf-8")
_VIEWER_CSS = (_VIEWER_DIR / "viewer.css").read_text(encoding="utf-8").rstrip("\n")
_VIEWER_JS = (_VIEWER_DIR / "viewer.js").read_text(encoding="utf-8").rstrip("\n")
_VIEWER_WORDMARK = (
    (_VIEWER_DIR / "spark-video-wordmark.svg")
    .read_text(encoding="utf-8")
    .strip()
    .replace(
        "<svg ",
        '<svg class="brand-wordmark" role="img" aria-label="Spark Video" ',
        1,
    )
)


def _html(payload: dict) -> str:
    data_json = json.dumps(payload, ensure_ascii=False, default=str)
    # Defend the closing </script> sentinel inside JSON.
    data_json = data_json.replace("</", "<\\/")
    title = html.escape(f"{payload['project']} · {payload['episode']} · viewer")
    marked_js = _MARKED_JS.replace("</script>", "<\\/script>")

    replacements = {
        "@@HTML_LANG@@": "zh-CN" if payload["viewer_language"] == "zh" else "en",
        "@@VIEWER_TITLE@@": title,
        "@@MARKED_JS@@": marked_js,
        "@@PROJECT@@": html.escape(payload["project"]),
        "@@EPISODE@@": html.escape(payload["episode"]),
        "@@SHOT_COUNT@@": str(len(payload["shots"])),
        "@@SPARK_VIDEO_WORDMARK@@": _VIEWER_WORDMARK,
        "@@VIEWER_DATA@@": data_json,
        "@@VIEWER_CSS@@": _VIEWER_CSS,
        "@@VIEWER_JS@@": _VIEWER_JS,
    }
    document = _VIEWER_TEMPLATE
    for marker, value in replacements.items():
        document = document.replace(marker, value)
    return document


def main() -> int:
    project, episode, no_open = _resolve_ids()
    ep_norm = normalize_episode_id(episode)
    ep_dir = episode_dir(project, episode)
    proj_dir = project_dir(project)

    storyboard = _load_json(ep_dir / "storyboard.json")
    calls = _collect_calls(ep_dir)
    storyboard_panels = _collect_storyboard_panels(ep_dir)

    # Try a few plausible filenames for the user's original premise. The
    # repo doesn't enforce a single canonical name yet — agents may write
    # it as initialPrompt.md (legacy) or premise.md (newer convention),
    # at the project or episode tier. First non-empty wins.
    premise_candidates = (
        ep_dir / "initialPrompt.md",
        ep_dir / "premise.md",
        proj_dir / "initialPrompt.md",
        proj_dir / "premise.md",
    )
    premise_text = None
    premise_source = None
    for cand in premise_candidates:
        text = _read_text(cand)
        if text and text.strip():
            premise_text = _rewrite_premise_image_paths(text, cand, ep_dir)
            premise_source = str(cand.relative_to(proj_dir.parent))
            break

    lore_sections = _collect_lore_sections(proj_dir, ep_dir)
    cast_groups = _collect_entity_groups(
        proj_dir=proj_dir,
        ep_dir=ep_dir,
        folder_name="cast",
        md_name="cast.md",
        manifest_name="cast.json",
    )
    set_groups = _collect_entity_groups(
        proj_dir=proj_dir,
        ep_dir=ep_dir,
        folder_name="movie-set",
        md_name="set.md",
        manifest_name="movie_set.json",
    )
    prop_groups = _collect_entity_groups(
        proj_dir=proj_dir,
        ep_dir=ep_dir,
        folder_name="props",
        md_name="prop.md",
        manifest_name="props.json",
    )

    # ``direction.json`` is the canonical director-skill output. Accept the
    # common ``director.json`` spelling as an explicit override so the viewer
    # does not silently show stale or empty directorial intent.
    direction_path = next(
        (
            path for path in (
                ep_dir / "director.json",
                ep_dir / "direction.json",
            )
            if path.is_file()
        ),
        None,
    )

    wan_site = active_wan_site(_HERE.parent)
    prompt_language = read_project_prompt_language(ep_dir)
    viewer_language = (
        prompt_language
        if prompt_language in {"en", "zh"}
        else ("zh" if wan_site == "cn" else "en")
    )
    payload = {
        "project": project,
        "episode": ep_norm,
        "prompt_language": prompt_language,
        "wan_site": wan_site,
        "viewer_language": viewer_language,
        "premise": premise_text,
        "premise_source": premise_source,
        "lore": _read_text(proj_dir / "lore.md"),
        "lore_sections": lore_sections,
        "direction": _load_json(direction_path) if direction_path else None,
        "direction_source": direction_path.name if direction_path else None,
        "script": _read_text(ep_dir / "script.md"),
        "scenes": _collect_scenes(ep_dir),
        "cast_groups": cast_groups,
        "set_groups": set_groups,
        "prop_groups": prop_groups,
        "cast": _flatten_entity_groups(cast_groups),
        "sets": _flatten_entity_groups(set_groups),
        "props": _flatten_entity_groups(prop_groups),
        "bgm": _collect_bgm(proj_dir, ep_dir),
        "audio": storyboard.get("audio") if storyboard else None,
        "video_model": storyboard.get("video_model") if storyboard else None,
        "shots": _collect_shots(
            ep_dir,
            storyboard,
            calls.get("sent_by_shot_ver"),
            calls.get("execution_by_shot_ver"),
            storyboard_panels,
        ),
        "calls": calls,
        "final": _collect_final(ep_dir, project, ep_norm),
    }

    out = ep_dir / "viewer.html"
    out.write_text(_html(payload), encoding="utf-8")
    print(f"[viewer] wrote {out}")

    if not no_open and platform.system() == "Darwin":
        try:
            subprocess.run(["open", str(out)], check=False)
        except Exception as e:
            print(f"[viewer] open failed: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
