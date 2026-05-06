"""Cast (角色) management.

Two-tier discovery (layered):

  1. **Project-level** ``projects/<id>/cast/`` — overrides matching names
  2. **Global**       ``./cast/``               — fallback / shared pool

Filename convention (matched by stem before the FIRST dot):

    cast/钱夫人.webp                ← portrait, default view
    cast/钱夫人.正面.webp           ← portrait, tagged view
    cast/钱夫人.侧面.webp
    cast/钱夫人.mp3                 ← voice sample, default
    cast/钱夫人.愤怒.mp3            ← voice sample, tagged
    cast/钱夫人.md                  ← soul card

If a character has more than one portrait, the CLI builds a grid composite
(``<id>.grid.png``) and feeds that to Wan as ``reference_image`` — Wan
explicitly supports multi-pane reference images.

If more than one voice sample exists, they're concatenated (and trimmed to
≤10s, the r2v ``reference_voice`` limit) into ``<id>.mix.mp3``.

Each character has an **ASCII id** used for OSS paths (so OSS URLs never
contain Chinese — that breaks several CDN / proxy paths and is awkward for
debugging). Display name (e.g. "钱夫人") is preserved everywhere the agent
sees it; only the upload filename is sanitized.

Composites and ASCII-renamed singletons are written to
``projects/<id>/cast_built/`` (per project, never mutating the user's
input dirs).
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image
from rich.console import Console

from . import soul as soul_mod, state, upload as up
from .config import SETTINGS

console = Console()

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
AUDIO_EXTS = {".mp3", ".wav"}
VOICE_MAX_S = 10.0  # r2v reference_voice upper bound


@dataclass
class Character:
    name: str
    id: str = ""  # ASCII slug used for OSS paths; populated in init_project
    images_local: list[str] = field(default_factory=list)
    audios_local: list[str] = field(default_factory=list)
    soul_local: str | None = None
    image_local: str | None = None  # final local file we upload (always ASCII basename)
    audio_local: str | None = None
    image_url: str | None = None
    audio_url: str | None = None
    soul: dict[str, Any] | None = None
    composite_image: bool = False
    composite_audio: bool = False
    source: str = "global"  # "global" | "project"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

_SKIP_NAMES = {"readme.md", "readme", ".gitkeep", ".ds_store"}

_ID_OK = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _is_ascii_safe(s: str) -> bool:
    """ASCII alnum + _ - only — safe as both filename and OSS path."""
    return bool(s) and all(c.isascii() and (c.isalnum() or c in "_-") for c in s)


def derive_id(name: str, *, soul_id: str | None = None) -> str:
    """Pick an ASCII slug for OSS paths.

    Priority:
      1. soul_id (validated against [a-z0-9_-]+)
      2. name itself if already ASCII-safe
      3. lowercased ASCII transliteration of name where possible
      4. cast_<6-char-hash> (deterministic by name)
    """
    if soul_id:
        sid = soul_id.strip().lower()
        if _ID_OK.match(sid):
            return sid
        console.print(f"[yellow]soul id {soul_id!r} ignored: must match [a-z0-9_-]+[/]")
    if _is_ascii_safe(name):
        return name.lower()
    # Fallback: stable hash. Display name stays in UI/prompt; this only
    # affects local cache filename + OSS upload path.
    h = hashlib.sha256(name.encode("utf-8")).hexdigest()[:6]
    return f"cast_{h}"


def _stem_of(path: Path) -> str:
    """Stem before the FIRST dot.  '钱夫人.愤怒.mp3' → '钱夫人'."""
    name = path.name
    head = name.split(".", 1)[0]
    return head if head else path.stem


def _scan_dir(d: Path, source: str) -> dict[str, dict[str, Any]]:
    """Collect images / audios / soul keyed by character stem."""
    out: dict[str, dict[str, Any]] = {}
    if not d.exists():
        return out
    for p in sorted(d.iterdir()):
        if p.is_dir():
            continue
        if p.name.lower() in _SKIP_NAMES:
            continue
        ext = p.suffix.lower()
        stem = _stem_of(p)
        if not stem:
            continue
        bucket = out.setdefault(stem, {"images": [], "audios": [], "soul": None, "source": source})
        if ext in IMAGE_EXTS:
            bucket["images"].append(p)
        elif ext in AUDIO_EXTS:
            bucket["audios"].append(p)
        elif ext == ".md":
            # only honor a clean '<name>.md', not '<name>.<tag>.md'
            if p.name == f"{stem}.md":
                bucket["soul"] = p
    return out


def _merge(global_buckets: dict, project_buckets: dict) -> dict[str, dict[str, Any]]:
    """Layered merge:
       - Project tier characters not in global → added as 'project'.
       - Project tier characters that also exist globally → MERGED:
         project images/audios *prepended* (so they're chosen first), and any
         project soul card overrides the global one. The merged char is
         tagged source='project' to surface the override.
       - Global-only characters → kept as 'global'.
    """
    merged: dict[str, dict[str, Any]] = {}
    for stem, b in global_buckets.items():
        merged[stem] = {
            "images": list(b["images"]),
            "audios": list(b["audios"]),
            "soul": b["soul"],
            "source": "global",
        }
    for stem, pb in project_buckets.items():
        if stem in merged:
            gb = merged[stem]
            gb["images"] = list(pb["images"]) + gb["images"]
            gb["audios"] = list(pb["audios"]) + gb["audios"]
            if pb["soul"]:
                gb["soul"] = pb["soul"]
            gb["source"] = "project"  # project tier touched it
        else:
            merged[stem] = {
                "images": list(pb["images"]),
                "audios": list(pb["audios"]),
                "soul": pb["soul"],
                "source": "project",
            }
    return merged


# ---------------------------------------------------------------------------
# Composites
# ---------------------------------------------------------------------------

def _build_grid(images: list[Path], out: Path, *, max_side: int = 1280) -> Path:
    """Compose N (>=2) portraits into a grid PNG. 2, 4, 9 panes supported best."""
    if len(images) < 2:
        raise ValueError("_build_grid expects 2+ images; single images should be copied directly.")
    out.parent.mkdir(parents=True, exist_ok=True)
    n = len(images)
    # pick grid dims
    if n == 2:
        cols, rows = 2, 1
    elif n <= 4:
        cols, rows = 2, 2
    else:
        cols, rows = 3, 3
    cell_w = max_side // cols
    cell_h = max_side // rows

    canvas = Image.new("RGB", (cell_w * cols, cell_h * rows), color=(20, 20, 20))
    for i, p in enumerate(images[: cols * rows]):
        try:
            im = Image.open(p).convert("RGB")
        except Exception as e:
            console.print(f"[yellow]grid: skip {p.name} ({e})[/]")
            continue
        im.thumbnail((cell_w, cell_h), Image.LANCZOS)
        x = (i % cols) * cell_w + (cell_w - im.width) // 2
        y = (i // cols) * cell_h + (cell_h - im.height) // 2
        canvas.paste(im, (x, y))

    canvas.save(out, format="PNG", optimize=True)
    return out


def _audio_duration_s(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _build_voice_mix(audios: list[Path], out: Path, *, max_s: float = VOICE_MAX_S) -> Path:
    """Concatenate 2+ audios via ffmpeg, then trim head to <= max_s.

    We deliberately keep it simple — Wan only wants a *timbre* sample, not a
    coherent dialog. If the concat overflows max_s we just cut.
    """
    if len(audios) < 2:
        raise ValueError("_build_voice_mix expects 2+ audios; single audio should be copied directly.")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not on PATH; install with `brew install ffmpeg`.")
    out.parent.mkdir(parents=True, exist_ok=True)

    # First, concat losslessly via demuxer (best when same codec/sr).
    listfile = out.with_suffix(".concat.txt")
    listfile.write_text(
        "\n".join(f"file '{a.resolve()}'" for a in audios), encoding="utf-8"
    )
    concat_mp3 = out.with_suffix(".concat.mp3")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(listfile), "-c:a", "libmp3lame", "-b:a", "192k",
        str(concat_mp3),
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    # Then cap at max_s.
    cmd2 = [
        "ffmpeg", "-y", "-i", str(concat_mp3),
        "-t", f"{max_s}", "-c:a", "libmp3lame", "-b:a", "192k",
        str(out),
    ]
    subprocess.run(cmd2, check=True, capture_output=True)

    listfile.unlink(missing_ok=True)
    concat_mp3.unlink(missing_ok=True)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def discover(*, project_id: str | None = None, global_dir: Path | str = "./cast") -> list[Character]:
    """Layered discovery — project tier overrides global tier."""
    g_dir = Path(global_dir).resolve()
    g_buckets = _scan_dir(g_dir, "global")

    p_buckets: dict = {}
    if project_id:
        p_dir = SETTINGS.projects_dir / project_id / "cast"
        p_buckets = _scan_dir(p_dir, "project")

    merged = _merge(g_buckets, p_buckets)

    chars: list[Character] = []
    for stem, b in sorted(merged.items()):
        images: list[Path] = b.get("images", []) or []
        audios: list[Path] = b.get("audios", []) or []
        if not images:
            console.print(f"[yellow]skip {stem}: no portrait[/]")
            continue

        soul_path: Path | None = b.get("soul")
        soul_dict: dict | None = None
        if soul_path:
            try:
                soul_dict = soul_mod.parse(soul_path).to_dict()
            except Exception as e:
                console.print(f"[red]soul parse failed for {stem}: {e}[/]")

        chars.append(
            Character(
                name=stem,
                images_local=[str(p) for p in images],
                audios_local=[str(p) for p in audios],
                soul_local=str(soul_path) if soul_path else None,
                soul=soul_dict,
                source=b.get("source", "global"),
            )
        )
    return chars


def _ensure_ascii_basename(src: Path, build_dir: Path, *, cid: str) -> Path:
    """If src has a non-ASCII basename, copy it to build_dir/<cid>.<ext>.

    Otherwise return src as-is. Skips re-copy if a fresh-enough cached copy
    already exists.
    """
    if _is_ascii_safe(src.stem) and _is_ascii_safe(src.suffix.lstrip(".")):
        return src
    dst = build_dir / f"{cid}{src.suffix.lower()}"
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return dst


def init_project(
    project_id: str,
    cast_dir: Path | str = "./cast",
    *,
    do_upload: bool = True,
) -> dict:
    chars = discover(project_id=project_id, global_dir=cast_dir)
    if not chars:
        raise RuntimeError(f"no characters found in {cast_dir} or projects/{project_id}/cast")

    build_dir = state.project_dir(project_id) / "cast_built"
    build_dir.mkdir(parents=True, exist_ok=True)

    seen_ids: dict[str, str] = {}
    for c in chars:
        # ---------- derive ASCII id ---------------------------------------
        soul_id = (c.soul or {}).get("front", {}).get("id") if c.soul else None
        c.id = derive_id(c.name, soul_id=soul_id)
        if c.id in seen_ids and seen_ids[c.id] != c.name:
            # collision (e.g. two distinct characters whose names hash-collide).
            extra = hashlib.sha256(c.name.encode("utf-8")).hexdigest()[6:10]
            c.id = f"{c.id}_{extra}"
        seen_ids[c.id] = c.name

        # ---------- portraits → 1 file ------------------------------------
        if len(c.images_local) == 1:
            src = Path(c.images_local[0])
            c.image_local = str(_ensure_ascii_basename(src, build_dir, cid=c.id))
        else:
            grid = build_dir / f"{c.id}.grid.png"
            _build_grid([Path(p) for p in c.images_local], grid)
            c.image_local = str(grid)
            c.composite_image = True
            console.print(f"[cyan]· {c.name} ({c.id}): composed {len(c.images_local)}-pane grid[/]")

        # ---------- audios → 1 file ---------------------------------------
        if not c.audios_local:
            c.audio_local = None
        elif len(c.audios_local) == 1:
            src = Path(c.audios_local[0])
            # Trim single audio to ≤10s if needed (r2v limit)
            dur = _audio_duration_s(src)
            if dur > VOICE_MAX_S:
                trimmed = build_dir / f"{c.id}.trimmed.mp3"
                cmd = [
                    "ffmpeg", "-y", "-i", str(src),
                    "-t", f"{VOICE_MAX_S}", "-c:a", "libmp3lame", "-b:a", "192k",
                    str(trimmed),
                ]
                subprocess.run(cmd, check=True, capture_output=True)
                c.audio_local = str(trimmed)
                console.print(f"[cyan]· {c.name} ({c.id}): trimmed voice from {dur:.1f}s to {VOICE_MAX_S}s[/]")
            else:
                c.audio_local = str(_ensure_ascii_basename(src, build_dir, cid=c.id))
        else:
            mix = build_dir / f"{c.id}.mix.mp3"
            _build_voice_mix([Path(p) for p in c.audios_local], mix)
            c.audio_local = str(mix)
            c.composite_audio = True
            console.print(f"[cyan]· {c.name} ({c.id}): mixed {len(c.audios_local)} voice samples[/]")

        # ---------- upload ------------------------------------------------
        if do_upload:
            console.print(f"[cyan]uploading {c.name} ({c.id}) image…[/]")
            c.image_url = up.upload(c.image_local)
            if c.audio_local:
                console.print(f"[cyan]uploading {c.name} ({c.id}) voice…[/]")
                c.audio_url = up.upload(c.audio_local)

    payload = {
        "project_id": project_id,
        "global_cast_dir": str(Path(cast_dir).resolve()),
        "project_cast_dir": str((SETTINGS.projects_dir / project_id / "cast").resolve()),
        "characters": [asdict(c) for c in chars],
    }
    state.write_json(project_id, "cast.json", payload)
    state.merge_state(project_id, {
        "cast_count": len(chars),
        "cast_uploaded": do_upload,
        "cast_with_soul": sum(1 for c in chars if c.soul),
        "cast_overrides_global": sum(1 for c in chars if c.source == "project"),
    })
    return payload


def load(project_id: str) -> dict:
    data = state.read_json(project_id, "cast.json")
    if not data:
        raise FileNotFoundError(
            f"cast.json missing for project '{project_id}'. "
            f"Run:\n    videogen cast init --project {project_id}\n"
            "(point --dir at your cast folder if it's not ./cast)"
        )
    return data
