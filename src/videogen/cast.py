"""Cast (角色) management.

Convention: ./cast/<NAME>.<ext> — pair .jpg/.png + .mp3/.wav by stem.
Example:
    ./cast/佟掌柜.jpg
    ./cast/佟掌柜.mp3
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from rich.console import Console

from . import state, upload as up

console = Console()

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
AUDIO_EXTS = {".mp3", ".wav"}


@dataclass
class Character:
    name: str
    image_local: str
    audio_local: str | None
    image_url: str | None = None  # populated after upload
    audio_url: str | None = None


def discover(cast_dir: Path) -> list[Character]:
    cast_dir = Path(cast_dir).resolve()
    if not cast_dir.exists():
        raise FileNotFoundError(cast_dir)

    by_stem: dict[str, dict[str, Path]] = {}
    for p in cast_dir.iterdir():
        if p.suffix.lower() in IMAGE_EXTS:
            by_stem.setdefault(p.stem, {})["image"] = p
        elif p.suffix.lower() in AUDIO_EXTS:
            by_stem.setdefault(p.stem, {})["audio"] = p

    chars: list[Character] = []
    for stem, parts in sorted(by_stem.items()):
        if "image" not in parts:
            console.print(f"[yellow]skip {stem}: missing image[/]")
            continue
        chars.append(
            Character(
                name=stem,
                image_local=str(parts["image"]),
                audio_local=str(parts["audio"]) if "audio" in parts else None,
            )
        )
    return chars


def init_project(project_id: str, cast_dir: Path | str = "./cast", *, do_upload: bool = True) -> dict:
    chars = discover(Path(cast_dir))
    if not chars:
        raise RuntimeError(f"no characters found in {cast_dir}")

    if do_upload:
        for c in chars:
            console.print(f"[cyan]uploading {c.name} image…[/]")
            c.image_url = up.upload(c.image_local)
            if c.audio_local:
                console.print(f"[cyan]uploading {c.name} voice…[/]")
                c.audio_url = up.upload(c.audio_local)

    payload = {
        "project_id": project_id,
        "cast_dir": str(Path(cast_dir).resolve()),
        "characters": [asdict(c) for c in chars],
    }
    state.write_json(project_id, "cast.json", payload)
    state.merge_state(project_id, {"cast_count": len(chars), "cast_uploaded": do_upload})
    return payload


def load(project_id: str) -> dict:
    data = state.read_json(project_id, "cast.json")
    if not data:
        raise FileNotFoundError(
            f"cast.json missing for project {project_id}; run `videogen cast init` first."
        )
    return data
