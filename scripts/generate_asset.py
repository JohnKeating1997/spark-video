# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Generate a cast, set, or prop image and retain its Wan source metadata.

Usage:
    uv run scripts/generate_asset.py cast --name "Ethan Cole" --prompt "..."
    uv run scripts/generate_asset.py set --name "inn-lobby-day" --prompt "..."
    uv run scripts/generate_asset.py prop --name "red-envelope-intact" --prompt "..."
    uv run scripts/generate_asset.py cast --name "Ethan Cole" --episode \
        --image "projects/demo/cast/Ethan Cole/portrait1.png" \
        --generation-mode reference --prompt "change the costume"

The wrapper writes ``.wan-generations.jsonl`` beside the downloaded images.
Each candidate is linked to its stable CDN URL by SHA-256, so renaming a
chosen candidate does not break the later manifest rebuild.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from lib.cli import active_wan_site, wan_cmd, wan_media_tag  # noqa: E402
from lib.env import load_pwd_dotenv  # noqa: E402
from lib.prompt_compiler import (  # noqa: E402
    LEGACY_VISUAL_MEDIA,
    VALID_VISUAL_MEDIA,
    compatible_art_direction,
    read_lore_front,
    require_compatible_art_direction,
    require_visual_medium,
    rendering_instruction,
    resolve_visual_medium,
    validate_reference_tags,
)

load_pwd_dotenv()

_LOG_NAME = ".wan-generations.jsonl"
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_KIND_DIRS = {"cast": "cast", "set": "movie-set", "prop": "props"}
_KIND_CARDS = {
    "cast": ("cast.md", "soul.md"),
    "set": ("set.md",),
    "prop": ("prop.md",),
}


def _projects_root() -> Path:
    return Path(os.environ.get("VIDEOGEN_PROJECTS_DIR", "./projects")).resolve()


def _project_dir() -> Path:
    project = os.environ.get("SPARK_VIDEO_PROJECT")
    if not project:
        raise RuntimeError("SPARK_VIDEO_PROJECT must be set")
    return _projects_root() / project


def _episode_dir() -> Path:
    episode = os.environ.get("SPARK_VIDEO_EPISODE")
    if not episode:
        raise RuntimeError("SPARK_VIDEO_EPISODE must be set with --episode")
    episode_id = episode if episode.startswith("episode-") else f"episode-{episode}"
    return _project_dir() / episode_id


def _asset_dir(kind: str, name: str, *, episode: bool) -> Path:
    base = _episode_dir() if episode else _project_dir()
    return base / _KIND_DIRS[kind] / name


def _require_episode_card(kind: str, name: str, asset_dir: Path) -> None:
    """Prevent accidental episode overrides made of orphaned images only."""
    if any((asset_dir / filename).is_file() for filename in _KIND_CARDS[kind]):
        return
    project_asset = _project_dir() / _KIND_DIRS[kind] / name
    project_hint = (
        f" A project-global asset already exists at {project_asset}; remove "
        "--episode to generate there."
        if project_asset.exists()
        else ""
    )
    card_names = " or ".join(_KIND_CARDS[kind])
    raise RuntimeError(
        f"--episode requires an episode-local {card_names} in {asset_dir}. "
        f"Scaffold the episode asset first if this is an intentional override."
        f"{project_hint}"
    )


def _json_from_stdout(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {"value": value}
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
    raise RuntimeError(f"wan returned non-JSON output: {text[-1000:]}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _result_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    values = payload.get("result") or []
    if not values and isinstance(payload.get("task"), dict):
        values = payload["task"].get("taskResult") or []
    return [value for value in values if isinstance(value, dict)]


def _result_url(result: dict[str, Any]) -> str | None:
    for key in ("downloadUrl", "urlWithoutLogo", "url"):
        value = result.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


def _candidate_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = _result_items(payload)
    candidates: list[dict[str, Any]] = []
    for fallback_index, item in enumerate(payload.get("savedFiles") or []):
        if isinstance(item, dict):
            raw_path = item.get("path")
            raw_index = item.get("index", fallback_index)
        else:
            raw_path = item
            raw_index = fallback_index
        if not isinstance(raw_path, str):
            continue
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in _IMAGE_SUFFIXES:
            continue
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            index = fallback_index
        result = results[index] if 0 <= index < len(results) else {}
        image_url = _result_url(result)
        if not image_url and isinstance(item, dict):
            value = item.get("url")
            image_url = value if isinstance(value, str) else None
        candidates.append({
            "index": index,
            "path": str(path),
            "sha256": _sha256(path),
            "image_url": image_url,
            "resource_id": result.get("resourceId"),
        })
    return candidates


def _append_generation_log(
    asset_dir: Path,
    *,
    task_id: str,
    command: str,
    prompt: str,
    references: list[str],
    generation_mode: str | None,
    candidates: list[dict[str, Any]],
) -> Path:
    record = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "taskId": task_id,
        "image_urls": [
            candidate["image_url"]
            for candidate in candidates
            if candidate.get("image_url")
        ],
        "command": command,
        "prompt": prompt,
        "references": references,
        "generation_mode": generation_mode,
        "candidates": candidates,
    }
    log_path = asset_dir / _LOG_NAME
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return log_path


def _persist_source_images(args: argparse.Namespace, asset_dir: Path) -> list[str]:
    """Keep user inputs below source/ so manifests never select them as assets."""
    references = list(args.image or [])
    if not args.source_image:
        return references
    if args.kind != "cast":
        raise RuntimeError("--source-image is only valid for cast generation")
    source_dir = asset_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    for index, raw in enumerate(args.source_image, 1):
        source = Path(raw).expanduser().resolve()
        if not source.is_file() or source.suffix.lower() not in _IMAGE_SUFFIXES:
            raise RuntimeError(f"invalid cast source image: {raw}")
        target = source_dir / f"source-{index:02d}{source.suffix.lower()}"
        if source != target.resolve():
            shutil.copy2(source, target)
        references.append(str(target))
    return references


def _build_command(
    args: argparse.Namespace,
    asset_dir: Path,
    references: list[str],
) -> tuple[list[str], str]:
    command = wan_cmd(_HERE.parent)
    if references:
        command += ["image2image"]
        if len(references) == 1:
            command += ["--image", references[0]]
        else:
            command += ["--images", ",".join(references)]
        command += ["--generation-mode", args.generation_mode]
    else:
        command += ["text2image"]
    lore_dir = _episode_dir() if args.episode else _project_dir()
    lore = read_lore_front(lore_dir)
    requested_medium = (
        require_visual_medium(args.visual_medium)
        if args.visual_medium else None
    )
    project_raw = lore.get("visual_medium")
    project_medium = (
        require_visual_medium(project_raw)
        if project_raw is not None and str(project_raw).strip() else None
    )
    if requested_medium:
        medium = requested_medium
    elif project_medium == "mixed":
        raise ValueError(
            "mixed projects require --visual-medium on each generated asset "
            "so its concrete rendering medium is explicit"
        )
    else:
        medium = resolve_visual_medium(
            project_default=project_medium,
            fallback_text=args.prompt,
        )
    require_compatible_art_direction(lore, medium)
    site = active_wan_site(_HERE.parent) if references else "intl"
    configured_language = str(lore.get("prompt_language") or "").strip().lower()
    language = (
        configured_language
        if configured_language in {"en", "zh"}
        else ("zh" if site == "cn" else "en")
    )
    lines = [
        "任务：" if language == "zh" else "Task:",
        {
            "cast": "生成角色参考资产。" if language == "zh" else "Create a character reference asset.",
            "set": "生成场景参考资产。" if language == "zh" else "Create a location reference asset.",
            "prop": "生成道具参考资产。" if language == "zh" else "Create a prop reference asset.",
        }[args.kind],
        rendering_instruction(medium, language=language),
    ]
    art_direction = compatible_art_direction(lore, medium)
    if art_direction:
        lines.append(("美术方向：" if language == "zh" else "Art direction: ") + "; ".join(art_direction))
    if references:
        tags = [wan_media_tag("image", index, site=site)
                for index in range(1, len(references) + 1)]
        lines.extend([
            "",
            "参考图：" if language == "zh" else "References:",
            ("、" if language == "zh" else ", ").join(tags),
            (
                "参考图是已锁定外观的权威来源；除非请求明确要求变更，否则不要重新设计身份、发型、服装、布局或外形。"
                if language == "zh" else
                "References are authoritative for locked appearance. Do not redesign identity, hair, costume, layout, or shape unless the request explicitly asks for that change."
            ),
        ])
    lines.extend(["", "要求：" if language == "zh" else "Request:", args.prompt.rstrip()])
    if args.source_image:
        source_start = len(args.image) + 1
        source_tags = tags[source_start - 1:]
        source_list = "、".join(source_tags) if language == "zh" else ", ".join(source_tags)
        lines.extend([
            "",
            "源图外观锁定：" if language == "zh" else "Source appearance lock:",
            (
                f"{source_list} 是人物身份、脸型、五官、发型、眼镜、服装、配饰、体型和年龄感的唯一权威来源。"
                if language == "zh" else
                f"{source_list} is the sole authority for identity, face, facial features, hair, glasses, costume, accessories, body type, and apparent age."
            ),
        ])
        if args.allow_source_appearance_change:
            lines.append(
                "仅执行要求中明确提出的外观变更，其余外观必须保持源图不变。"
                if language == "zh" else
                "Apply only appearance changes explicitly requested above; preserve every other source appearance attribute."
            )
        else:
            lines.append(
                "忽略要求中任何与源图冲突的外观描述；不得重新设计或替换上述人物属性。要求只能影响姿势、构图、背景、光线和输出格式。"
                if language == "zh" else
                "Ignore any appearance description in the request that conflicts with the source. Do not redesign or replace those character attributes. The request may affect only pose, composition, background, lighting, and output format."
            )
    prompt = "\n".join(lines).strip()
    if references:
        validate_reference_tags(
            prompt,
            tag_prefix=tags[0][:-1],
            reference_count=len(references),
        )
    command += [
        "--prompt", prompt,
        "--ratio", args.ratio,
        "--resolution", args.resolution,
    ]
    if args.model:
        command += ["--model", args.model]
    if args.dry_run:
        command += ["--dry-run"]
    else:
        command += [
            "--wait", "--save", "--save-dir", str(asset_dir),
            "--timeout", str(args.timeout),
        ]
    command += ["--output", "json"]
    return command, prompt


def cmd_generate(args: argparse.Namespace) -> int:
    try:
        asset_dir = _asset_dir(args.kind, args.name, episode=args.episode)
        if args.episode:
            _require_episode_card(args.kind, args.name, asset_dir)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    asset_dir.mkdir(parents=True, exist_ok=True)
    try:
        references = _persist_source_images(args, asset_dir)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        command, prompt = _build_command(args, asset_dir, references)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=args.timeout + 30,
        check=False,
    )
    if proc.returncode != 0:
        print((proc.stderr or proc.stdout).strip()[-2000:], file=sys.stderr)
        return proc.returncode
    payload = _json_from_stdout(proc.stdout)
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if payload.get("ok") is False:
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    candidates = _candidate_records(payload)
    candidates_with_urls = [item for item in candidates if item.get("image_url")]
    if not candidates or len(candidates_with_urls) != len(candidates):
        print(
            "ERROR: wan succeeded but candidate path/URL metadata was incomplete; "
            f"taskId={payload.get('taskId', 'unknown')}",
            file=sys.stderr,
        )
        return 1
    task_id = str(payload.get("taskId") or "")
    if not task_id:
        print("ERROR: wan succeeded but returned no taskId", file=sys.stderr)
        return 1
    log_path = _append_generation_log(
        asset_dir,
        task_id=task_id,
        command="image2image" if references else "text2image",
        prompt=prompt,
        references=references,
        generation_mode=args.generation_mode if references else None,
        candidates=candidates,
    )
    saved_files = [item["path"] for item in candidates]
    preview_markdown = "\n".join(
        f"![Generated {args.kind} candidate {index}](<{path}>)"
        for index, path in enumerate(saved_files, 1)
    )
    print(json.dumps({
        "ok": True,
        "kind": args.kind,
        "name": args.name,
        "asset_dir": str(asset_dir),
        "taskId": task_id,
        "image_urls": [item["image_url"] for item in candidates],
        "savedFiles": saved_files,
        "candidate_count": len(saved_files),
        "selection_required": False,
        "selection_status": "needs_agent_default",
        "next_action": (
            "Review every savedFiles candidate and record one Agent default "
            "with asset-recommend. Rebuild manifests and Viewer, tell the user "
            "they may change the default there, and continue without waiting. "
            "Do not rename or delete candidates."
        ),
        # The caller can paste this field into its response to display the
        # generated local images in Codex or another Markdown-capable agent.
        "preview_markdown": preview_markdown,
        "generation_log": str(log_path),
    }, ensure_ascii=False, indent=2))
    return 0


def _add_asset_parser(
    sub: argparse._SubParsersAction,
    kind: str,
    *,
    default_ratio: str,
) -> None:
    parser = sub.add_parser(kind)
    parser.set_defaults(fn=cmd_generate, kind=kind)
    parser.add_argument("--name", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--episode", action="store_true")
    parser.add_argument("--image", action="append", default=[])
    parser.add_argument(
        "--source-image",
        action="append",
        default=[],
        help=("cast-only user reference; copied under source/ and used for "
              "reference generation, never selected as the final cast asset"),
    )
    parser.add_argument(
        "--generation-mode",
        choices=["imaginative", "reference", "standard"],
        default="reference",
    )
    parser.add_argument(
        "--allow-source-appearance-change",
        action="store_true",
        help=("allow explicit hair/costume/appearance edits to a cast "
              "--source-image; otherwise source appearance is locked"),
    )
    parser.add_argument("--ratio", default=default_ratio)
    parser.add_argument("--resolution", default="2K")
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--visual-medium",
        choices=sorted(VALID_VISUAL_MEDIA | LEGACY_VISUAL_MEDIA),
        default=None,
        help=(
            "asset-level medium override; otherwise inherit lore.visual_medium. "
            "Legacy illustration is accepted as 2d_animation"
        ),
    )
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--dry-run", action="store_true")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="kind", required=True)
    _add_asset_parser(sub, "cast", default_ratio="16:9")
    _add_asset_parser(sub, "set", default_ratio="16:9")
    _add_asset_parser(sub, "prop", default_ratio="1:1")
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
