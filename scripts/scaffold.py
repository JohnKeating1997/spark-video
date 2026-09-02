# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
scaffold.py — generate templates for episodes, scenes, lore, cast, sets, props.

Subcommands:
    episode --init          mkdir scaffold for projects/<p>/<ep>/
    lore --title "<title>"  scaffold projects/<p>/lore.md
    scene --num N           scaffold scenes/scene-NN.md (mode-specific)
    cast --name "Ethan Cole"      scaffold cast folder + cast.md template
    cast --fork --name "Ethan Cole" --drop-portraits   copy project cast to episode tier
                                                and optionally delete copied reference images
    set --name "inn-lobby-day"   scaffold movie-set folder + set.md
    prop --name "red-envelope-intact"  scaffold prop folder + prop.md
    cast-init               rebuild cast.json from project + episode tiers
    set-init                rebuild movie_set.json
    prop-init               rebuild props.json
    manifests               cast-init + set-init + prop-init
    asset-import            copy a local image into an asset's candidate set
    asset-recommend         record the Agent's active default candidate
    asset-select            choose the one image used by manifests + rendering
    mood-anchor             print lore.mood_anchor for piping into bl prompts

Respects SPARK_VIDEO_PROJECT / SPARK_VIDEO_EPISODE env vars.
Pass --episode to flag cast/set/prop as episode-tier.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from lib.env import load_pwd_dotenv  # noqa: E402

load_pwd_dotenv()


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_ASSET_DIRS = {"cast": "cast", "set": "movie-set", "prop": "props"}
_SELECTION_FILE = ".asset-selection.json"
_RECOMMENDATION_FILE = ".asset-recommendation.json"


def _projects_root() -> Path:
    return Path(os.environ.get("VIDEOGEN_PROJECTS_DIR", "./projects")).resolve()


def _project_dir() -> Path:
    proj = os.environ.get("SPARK_VIDEO_PROJECT")
    if not proj:
        print("ERROR: SPARK_VIDEO_PROJECT must be set", file=sys.stderr)
        sys.exit(2)
    return _projects_root() / proj


def _episode_dir(required: bool = True) -> Path:
    ep = os.environ.get("SPARK_VIDEO_EPISODE")
    if not ep and required:
        print("ERROR: SPARK_VIDEO_EPISODE must be set", file=sys.stderr)
        sys.exit(2)
    ep_id = ep if ep.startswith("episode-") else f"episode-{ep}"
    return _project_dir() / ep_id


# ----------------------------------------------------------- episode --init

def cmd_episode(args: argparse.Namespace) -> int:
    ep_dir = _episode_dir()
    for sub in ("scenes", "clips", "frames", "reviews", "logs", "final",
                "cast", "movie-set", "props"):
        (ep_dir / sub).mkdir(parents=True, exist_ok=True)
    proj_dir = _project_dir()
    for sub in ("cast", "movie-set", "props", "bgm"):
        (proj_dir / sub).mkdir(parents=True, exist_ok=True)
    print(f"scaffold ready at {ep_dir}/")
    return 0


# ---------------------------------------------------------------------- lore

LORE_TEMPLATE = """\
---
title: "{title}"
mood_anchor: "TBD — global lighting, palette, contrast, texture, atmosphere; no character-specific traits"
visual_style: "TBD — concrete treatment (e.g. stylized 3D CG, soft PBR materials, graphic facial proportions)"
visual_medium: "TBD — live_action | 2d_animation | 3d_animation | stop_motion | mixed"
genre: "TBD"
duration_target_s: 180
forbidden:
  - gore
  - explicit content
imagery_system:
  motifs: []
  highlight_elements: []
---

# {title}

## Worldbuilding

(Describe the project's world, era, and core premise here.)

## Protagonist arc

(Each character's core drive and long-term arc.)

## Visual anchor

`mood_anchor` is this project's most important visual-consistency lever — it is
appended to **every** shot prompt. Write it like a product tagline:
- Too broad: "cinematic"
- Too specific: "50mm lens, F1.8, 5600K white balance, Bayer filter"
- Just right: "warm streetlamps + shallow depth of field + wet pavement reflections, 90s Hong Kong film texture"
"""


def cmd_lore(args: argparse.Namespace) -> int:
    proj_dir = _project_dir()
    proj_dir.mkdir(parents=True, exist_ok=True)
    lore = proj_dir / "lore.md"
    if lore.exists() and not args.force:
        print(f"{lore} already exists. Use --force to overwrite.", file=sys.stderr)
        return 1
    lore.write_text(LORE_TEMPLATE.format(title=args.title or proj_dir.name))
    print(f"wrote {lore} — edit mood_anchor before any drafting")
    return 0


def cmd_mood_anchor(args: argparse.Namespace) -> int:
    """Print lore.mood_anchor for piping into bl prompts."""
    lore = _project_dir() / "lore.md"
    if not lore.exists():
        print("", end="")
        return 0
    # Crude frontmatter parse — no PyYAML dep
    text = lore.read_text()
    if not text.startswith("---"):
        return 0
    try:
        end = text.index("---", 3)
        fm = text[3:end]
    except ValueError:
        return 0
    for line in fm.splitlines():
        line = line.strip()
        if line.startswith("mood_anchor:"):
            val = line.split(":", 1)[1].strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            print(val, end="")
            return 0
    return 0


# --------------------------------------------------------------------- scene

DRAMA_TEMPLATE = """\
## Scene {n} — <location> (<time of day>)

**Characters**: <characters from cast.json>
**Pacing**: <external pace> (external) + <internal pace> (internal)
**Estimated duration**: 30s
**Backstory**: <one sentence — what characters carry into this scene>

**Plot**:
<2-4 sentences. Camera-visible action only.>

**Dialogue**:
- <CharacterA>: "<dialog>"
- <CharacterB>: "<dialog>"
"""

NARRATION_TEMPLATE = """\
## Scene {n} — <location> (<time of day>)

**Type**: narration
**Characters**: <characters appearing in any beat>
**Estimated duration**: 30s
**Backstory**: <one sentence>

**Beats**:
1. **Presenter**: "<short line in the approved presenter's voice>"
   **Audio source**: post_tts
   **Visual speech**: voiceover
   **Visual**: <filmable action + suggested duration 6-12s>
2. **Presenter**: "<next continuous line from the same presenter>"
   **Audio source**: post_tts
   **Visual speech**: voiceover
   **Visual**: <filmable action + suggested duration 6-12s>
"""


def cmd_scene(args: argparse.Namespace) -> int:
    ep_dir = _episode_dir()
    (ep_dir / "scenes").mkdir(parents=True, exist_ok=True)
    n = int(args.num)
    f = ep_dir / "scenes" / f"scene-{n:02d}.md"
    if f.exists() and not args.force:
        print(f"{f} already exists. Use --force to overwrite.", file=sys.stderr)
        return 1
    tpl = NARRATION_TEMPLATE if args.mode == "narration" else DRAMA_TEMPLATE
    f.write_text(tpl.format(n=n))
    print(f"wrote {f}")
    return 0


# ---------------------------------------------------------------------- cast

CAST_MD_TEMPLATE = """\
---
name: "{name}"
age: "TBD"
gender: "TBD"
visual_anchor: "TBD — one-line appearance for cast reference-sheet t2i"
voice_traits: "TBD"
dont:
  - "forbidden looks / wardrobe"
---

# {name}

## Personality

(A few sentences on personality arc, catchphrases, and motivation.)

## Visual anchor

`visual_anchor` should paste directly into a t2i prompt.
Default to a full-body standing character sheet / three-view reference,
not a face-only or front-only portrait.
Example: "a three-view drawing of a person and annotate it with an AI-generated, non-real-person watermark on the bottom, 28-year-old man, short hair, dark T-shirt, full-body character reference sheet, front view, side view, back view, same face and costume in all views, plain background, no other readable text."
"""


def cmd_cast(args: argparse.Namespace) -> int:
    if args.fork:
        return _cast_fork(args)
    base = _episode_dir() if args.episode else _project_dir()
    cast_dir = base / "cast" / args.name
    cast_dir.mkdir(parents=True, exist_ok=True)
    md = cast_dir / "cast.md"
    if md.exists() and not args.force:
        print(f"{md} already exists. Use --force to overwrite.", file=sys.stderr)
        return 1
    md.write_text(CAST_MD_TEMPLATE.format(name=args.name))
    print(f"scaffolded {cast_dir}/")
    print(f"  → edit {md}")
    print("  → generate with: uv run scripts/generate_asset.py cast")
    print(f"    --name {args.name!r} --prompt \"...\"")
    print(f"  → then run: uv run scripts/scaffold.py cast-init")
    return 0


def _cast_fork(args: argparse.Namespace) -> int:
    if not args.name:
        print("ERROR: --name required for --fork", file=sys.stderr)
        return 2
    src = _project_dir() / "cast" / args.name
    dst = _episode_dir() / "cast" / args.name
    if not src.exists():
        print(f"ERROR: project cast {src} does not exist", file=sys.stderr)
        return 2
    if dst.exists() and not args.force:
        print(f"{dst} already exists. Use --force to overwrite.", file=sys.stderr)
        return 1
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    if args.drop_portraits:
        for png in dst.glob("*.png"):
            png.unlink()
        for jpg in dst.glob("*.jpg"):
            jpg.unlink()
        print(f"  dropped cast reference images from {dst}/")
    print(f"forked {src} → {dst}")
    print(f"  next: wan image2image --generation-mode reference ... --save-dir {dst}/ --output json")
    print(f"        uv run scripts/scaffold.py cast-init")
    return 0


# ---------------------------------------------------------------------- set

SET_MD_TEMPLATE = """\
---
name: "{name}"
time_of_day: "TBD — day | dusk | night | dawn"
season: "TBD"
color_grade: "TBD — cool / warm / neutral / high-contrast neon / ..."
lighting: "TBD"
weather: "TBD"
---

# {name}

## Set description

(Materials, layout, key props, visual signature. One sentence reusable in a t2i prompt is ideal.)
"""


def cmd_set(args: argparse.Namespace) -> int:
    base = _episode_dir() if args.episode else _project_dir()
    set_dir = base / "movie-set" / args.name
    set_dir.mkdir(parents=True, exist_ok=True)
    md = set_dir / "set.md"
    if md.exists() and not args.force:
        print(f"{md} already exists. Use --force to overwrite.", file=sys.stderr)
        return 1
    md.write_text(SET_MD_TEMPLATE.format(name=args.name))
    print(f"scaffolded {set_dir}/")
    print(f"  → edit {md} (pin time_of_day / lighting / color_grade)")
    print("  → generate with: uv run scripts/generate_asset.py set")
    print(f"    --name {args.name!r} --prompt \"...\"")
    print(f"  → then run: uv run scripts/scaffold.py set-init")
    return 0


# --------------------------------------------------------------------- prop

PROP_MD_TEMPLATE = """\
---
name: "{name}"
state: "TBD — intact / crumpled / torn / closed / open / ..."
---

# {name}

## Prop description

(Material, color, shape, key details.)

⚠ One folder = one narrative state. If the same item has multiple states
   (intact → crumpled → torn), each state is a **separate folder**:
   red-envelope-intact / red-envelope-creased / red-envelope-torn.
"""


def cmd_prop(args: argparse.Namespace) -> int:
    base = _episode_dir() if args.episode else _project_dir()
    prop_dir = base / "props" / args.name
    prop_dir.mkdir(parents=True, exist_ok=True)
    md = prop_dir / "prop.md"
    if md.exists() and not args.force:
        print(f"{md} already exists. Use --force to overwrite.", file=sys.stderr)
        return 1
    md.write_text(PROP_MD_TEMPLATE.format(name=args.name))
    print(f"scaffolded {prop_dir}/")
    print(f"  → edit {md}")
    print("  → generate with: uv run scripts/generate_asset.py prop")
    print(f"    --name {args.name!r} --prompt \"...\"")
    print(f"  → then run: uv run scripts/scaffold.py prop-init")
    return 0


# ------------------------------------------------- manifest rebuild commands

def _read_selected_image(asset_dir: Path, images: list[str]) -> str | None:
    """Return the explicitly selected image when the sidecar is valid."""
    selection_path = asset_dir / _SELECTION_FILE
    try:
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    filename = selection.get("selected_image") if isinstance(selection, dict) else None
    if not isinstance(filename, str) or Path(filename).name != filename:
        return None
    candidate = str(asset_dir / filename)
    return candidate if candidate in images else None


def _write_selected_image(asset_dir: Path, image: Path) -> Path:
    selection_path = asset_dir / _SELECTION_FILE
    selection_path.write_text(
        json.dumps(
            {"version": 1, "selected_image": image.name},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return selection_path


def _write_recommended_image(asset_dir: Path, image: Path) -> Path:
    recommendation_path = asset_dir / _RECOMMENDATION_FILE
    recommendation_path.write_text(
        json.dumps(
            {"version": 1, "recommended_image": image.name, "recommended_by": "agent"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return recommendation_path


def _read_recommended_image(asset_dir: Path, images: list[str]) -> str | None:
    recommendation_path = asset_dir / _RECOMMENDATION_FILE
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
    candidate = str(asset_dir / filename)
    return candidate if candidate in images else None


def _asset_dir_for(kind: str, name: str, *, episode: bool) -> Path:
    base = _episode_dir() if episode else _project_dir()
    return base / _ASSET_DIRS[kind] / name


def _unique_import_path(asset_dir: Path, source: Path) -> Path:
    destination = asset_dir / source.name
    if not destination.exists():
        return destination
    try:
        if source.samefile(destination):
            return destination
    except OSError:
        pass
    index = 2
    while True:
        destination = asset_dir / f"{source.stem}-{index}{source.suffix.lower()}"
        if not destination.exists():
            return destination
        index += 1


def _rebuild_asset_manifest(kind: str, args: argparse.Namespace) -> int:
    return {
        "cast": cmd_cast_init,
        "set": cmd_set_init,
        "prop": cmd_prop_init,
    }[kind](args)


def cmd_asset_import(args: argparse.Namespace) -> int:
    source = Path(args.image).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in _IMAGE_SUFFIXES:
        print(f"ERROR: image not found or unsupported: {source}", file=sys.stderr)
        return 2
    asset_dir = _asset_dir_for(args.kind, args.name, episode=args.episode)
    if not asset_dir.is_dir():
        print(f"ERROR: asset folder does not exist: {asset_dir}", file=sys.stderr)
        return 2
    destination = _unique_import_path(asset_dir, source)
    try:
        already_present = source.samefile(destination)
    except OSError:
        already_present = False
    if not already_present:
        shutil.copy2(source, destination)
    print(f"added candidate {destination}")
    if args.select:
        _write_selected_image(asset_dir, destination)
        print(f"selected {destination.name} as the primary image")
        return _rebuild_asset_manifest(args.kind, args)
    print("primary image unchanged; run asset-select when this candidate is approved")
    return 0


def cmd_asset_select(args: argparse.Namespace) -> int:
    asset_dir = _asset_dir_for(args.kind, args.name, episode=args.episode)
    raw = Path(args.image).expanduser()
    image = raw.resolve() if raw.is_absolute() else (asset_dir / raw).resolve()
    try:
        image.relative_to(asset_dir.resolve())
    except ValueError:
        print("ERROR: selection must already be inside the asset folder", file=sys.stderr)
        return 2
    if not image.is_file() or image.suffix.lower() not in _IMAGE_SUFFIXES:
        print(f"ERROR: candidate image not found or unsupported: {image}", file=sys.stderr)
        return 2
    _write_selected_image(asset_dir, image)
    print(f"selected {image.name} as the primary image")
    return _rebuild_asset_manifest(args.kind, args)


def cmd_asset_recommend(args: argparse.Namespace) -> int:
    asset_dir = _asset_dir_for(args.kind, args.name, episode=args.episode)
    raw = Path(args.image).expanduser()
    image = raw.resolve() if raw.is_absolute() else (asset_dir / raw).resolve()
    try:
        image.relative_to(asset_dir.resolve())
    except ValueError:
        print("ERROR: recommendation must already be inside the asset folder", file=sys.stderr)
        return 2
    if not image.is_file() or image.suffix.lower() not in _IMAGE_SUFFIXES:
        print(f"ERROR: candidate image not found or unsupported: {image}", file=sys.stderr)
        return 2
    _write_recommended_image(asset_dir, image)
    print(f"recommended {image.name} as the active default")
    return 0

def _scan_tier_folders(tier_dir: Path, key_files: list[str]) -> dict[str, dict]:
    """Scan tier/<name>/ folders, return {name: {md_path, images, voice?}}."""
    out: dict[str, dict] = {}
    if not tier_dir.exists():
        return out
    for sub in sorted(tier_dir.iterdir()):
        if not sub.is_dir():
            continue
        md = None
        for kf in key_files:
            cand = sub / kf
            if cand.exists():
                md = cand
                break
        all_images = sorted(
            str(path)
            for path in sub.iterdir()
            if path.is_file()
            and path.suffix.lower() in _IMAGE_SUFFIXES
        )
        images = list(all_images)
        explicit_selection = _read_selected_image(sub, all_images)
        recommendation = _read_recommended_image(sub, all_images)
        if explicit_selection:
            images = [explicit_selection]
        elif recommendation:
            # The Agent recommendation is the active default. A later explicit
            # user selection supersedes it without deleting the alternates.
            images = [recommendation]
        if tier_dir.name == "cast":
            selected = [
                image for image in images
                if Path(image).stem.lower().startswith("portrait")
            ]
            # A source/ directory marks a user-derived cast. Until the user
            # selects a generated portrait, this is provenance, not a usable
            # downstream character asset. For legacy/manual casts without
            # source/, retain the existing filename-compatible behavior.
            if not explicit_selection and (selected or (sub / "source").is_dir()):
                images = selected
        voices = sorted([str(p) for p in sub.glob("*.mp3")] +
                        [str(p) for p in sub.glob("*.wav")] +
                        [str(p) for p in sub.glob("*.m4a")])
        metadata_by_hash: dict[str, dict] = {}
        generation_log = sub / ".wan-generations.jsonl"
        if generation_log.exists():
            for line in generation_log.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                task_id = record.get("taskId") or record.get("task_id")
                for candidate in record.get("candidates", []) or []:
                    digest = candidate.get("sha256")
                    image_url = candidate.get("image_url")
                    if isinstance(digest, str) and isinstance(image_url, str):
                        metadata_by_hash[digest] = {
                            "image_url": image_url,
                            "task_id": task_id,
                        }
        matched_urls: list[str | None] = []
        task_ids: list[str] = []
        for image in images:
            digest = hashlib.sha256()
            with Path(image).open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            metadata = metadata_by_hash.get(digest.hexdigest()) or {}
            image_url = metadata.get("image_url")
            task_id = metadata.get("task_id")
            matched_urls.append(image_url if isinstance(image_url, str) else None)
            if isinstance(task_id, str) and task_id not in task_ids:
                task_ids.append(task_id)
        entry = {
            "name": sub.name,
            "md_path": str(md) if md else None,
            "images": images,
            "voices": voices,
            "tier": tier_dir.parent.name if tier_dir.parent.name.startswith("episode") else "project",
        }
        if explicit_selection:
            entry["selected_image"] = explicit_selection
            entry["candidate_images"] = all_images
        elif recommendation:
            entry["selected_image"] = recommendation
            entry["recommended_image"] = recommendation
            entry["candidate_images"] = all_images
        # Keep images and image_urls positionally aligned. If a folder mixes a
        # generated image with an untracked manual file, fall back to local
        # paths instead of attaching the wrong remote URL to an image.
        if images and all(matched_urls):
            entry["image_urls"] = matched_urls
        if len(task_ids) == 1:
            entry["task_id"] = task_ids[0]
        elif task_ids:
            entry["task_ids"] = task_ids
        out[sub.name] = entry
    return out


def _merge_tiers(project_tier: dict, episode_tier: dict) -> dict:
    """Episode tier overrides project tier on name collision."""
    merged = dict(project_tier)
    merged.update(episode_tier)
    return merged


def cmd_cast_init(args: argparse.Namespace) -> int:
    proj = _scan_tier_folders(_project_dir() / "cast", ["cast.md", "soul.md"])
    ep_dir = _episode_dir(required=False) if os.environ.get("SPARK_VIDEO_EPISODE") else None
    epi = _scan_tier_folders(ep_dir / "cast", ["cast.md", "soul.md"]) if ep_dir else {}
    merged = _merge_tiers(proj, epi)
    out_path = (ep_dir or _project_dir()) / "cast.json"
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2))
    print(f"wrote {out_path} ({len(merged)} characters)")
    return 0


def cmd_set_init(args: argparse.Namespace) -> int:
    proj = _scan_tier_folders(_project_dir() / "movie-set", ["set.md"])
    ep_dir = _episode_dir(required=False) if os.environ.get("SPARK_VIDEO_EPISODE") else None
    epi = _scan_tier_folders(ep_dir / "movie-set", ["set.md"]) if ep_dir else {}
    merged = _merge_tiers(proj, epi)
    out_path = (ep_dir or _project_dir()) / "movie_set.json"
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2))
    print(f"wrote {out_path} ({len(merged)} sets)")
    return 0


def cmd_prop_init(args: argparse.Namespace) -> int:
    proj = _scan_tier_folders(_project_dir() / "props", ["prop.md"])
    ep_dir = _episode_dir(required=False) if os.environ.get("SPARK_VIDEO_EPISODE") else None
    epi = _scan_tier_folders(ep_dir / "props", ["prop.md"]) if ep_dir else {}
    merged = _merge_tiers(proj, epi)
    out_path = (ep_dir or _project_dir()) / "props.json"
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2))
    print(f"wrote {out_path} ({len(merged)} props)")
    return 0


def cmd_manifests(args: argparse.Namespace) -> int:
    rc = cmd_cast_init(args)
    rc |= cmd_set_init(args)
    rc |= cmd_prop_init(args)
    return rc


# ----------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ep = sub.add_parser("episode")
    p_ep.add_argument("--init", action="store_true")
    p_ep.set_defaults(fn=cmd_episode)

    p_lore = sub.add_parser("lore")
    p_lore.add_argument("--title", default=None)
    p_lore.add_argument("--force", action="store_true")
    p_lore.set_defaults(fn=cmd_lore)

    p_scene = sub.add_parser("scene")
    p_scene.add_argument("--num", required=True, type=int)
    p_scene.add_argument("--mode", choices=["drama", "narration"], default="drama")
    p_scene.add_argument("--force", action="store_true")
    p_scene.set_defaults(fn=cmd_scene)

    p_cast = sub.add_parser("cast")
    p_cast.add_argument("--name", required=True)
    p_cast.add_argument("--episode", action="store_true",
                        help="put under episode tier instead of project tier")
    p_cast.add_argument("--fork", action="store_true",
                        help="copy project cast to episode tier")
    p_cast.add_argument("--drop-portraits", action="store_true",
                        help="when --fork, delete copied cast reference images to force regen")
    p_cast.add_argument("--force", action="store_true")
    p_cast.set_defaults(fn=cmd_cast)

    p_set = sub.add_parser("set")
    p_set.add_argument("--name", required=True)
    p_set.add_argument("--episode", action="store_true")
    p_set.add_argument("--force", action="store_true")
    p_set.set_defaults(fn=cmd_set)

    p_prop = sub.add_parser("prop")
    p_prop.add_argument("--name", required=True)
    p_prop.add_argument("--episode", action="store_true")
    p_prop.add_argument("--force", action="store_true")
    p_prop.set_defaults(fn=cmd_prop)

    p_import = sub.add_parser("asset-import")
    p_import.add_argument("--kind", choices=sorted(_ASSET_DIRS), required=True)
    p_import.add_argument("--name", required=True)
    p_import.add_argument("--image", required=True)
    p_import.add_argument("--episode", action="store_true")
    p_import.add_argument("--select", action="store_true",
                          help="also choose the imported image as the primary")
    p_import.set_defaults(fn=cmd_asset_import)

    p_select = sub.add_parser("asset-select")
    p_select.add_argument("--kind", choices=sorted(_ASSET_DIRS), required=True)
    p_select.add_argument("--name", required=True)
    p_select.add_argument("--image", required=True,
                          help="candidate filename already inside the asset folder")
    p_select.add_argument("--episode", action="store_true")
    p_select.set_defaults(fn=cmd_asset_select)

    p_recommend = sub.add_parser("asset-recommend")
    p_recommend.add_argument("--kind", choices=sorted(_ASSET_DIRS), required=True)
    p_recommend.add_argument("--name", required=True)
    p_recommend.add_argument("--image", required=True,
                             help="candidate filename already inside the asset folder")
    p_recommend.add_argument("--episode", action="store_true")
    p_recommend.set_defaults(fn=cmd_asset_recommend)

    for name, fn in [("cast-init", cmd_cast_init), ("set-init", cmd_set_init),
                     ("prop-init", cmd_prop_init), ("manifests", cmd_manifests)]:
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)

    p_ma = sub.add_parser("mood-anchor")
    p_ma.set_defaults(fn=cmd_mood_anchor)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
