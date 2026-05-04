"""videogen — main Typer CLI.

Designed to be driven by Claude Code / Qwen Code via Skill + Slash Commands.
Every command produces JSON-friendly output for agent consumption.
"""
from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import cast as cast_mod, ffmpeg as ff, render as render_mod, state, wan
from .config import SETTINGS
from .storyboard import Shot, Storyboard

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Long-form AI video generator (Wan2.7) — driven by Claude Code Skills.",
)
console = Console()

# ---------- cast --------------------------------------------------------------
cast_app = typer.Typer(help="Manage characters in ./cast")
app.add_typer(cast_app, name="cast")


@cast_app.command("init")
def cast_init(
    project_id: str = typer.Option(..., "--project", "-p"),
    cast_dir: Path = typer.Option(Path("./cast"), "--dir"),
    no_upload: bool = typer.Option(False, "--no-upload", help="skip OSS upload (dry run)"),
):
    """Scan cast/ directory, upload images+voices, write cast.json."""
    payload = cast_mod.init_project(project_id, cast_dir, do_upload=not no_upload)
    table = Table(title=f"Cast for {project_id}")
    table.add_column("Name"); table.add_column("Image"); table.add_column("Voice"); table.add_column("Uploaded")
    for c in payload["characters"]:
        table.add_row(
            c["name"],
            Path(c["image_local"]).name,
            Path(c["audio_local"]).name if c["audio_local"] else "—",
            "✓" if c.get("image_url") else "—",
        )
    console.print(table)


@cast_app.command("ls")
def cast_ls(project_id: str = typer.Option(..., "--project", "-p")):
    data = cast_mod.load(project_id)
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


# ---------- storyboard --------------------------------------------------------
sb_app = typer.Typer(help="Storyboard validation/inspection")
app.add_typer(sb_app, name="storyboard")


@sb_app.command("validate")
def sb_validate(project_id: str = typer.Option(..., "--project", "-p")):
    """Validate ./projects/<id>/storyboard.json against the schema."""
    raw = state.read_json(project_id, "storyboard.json")
    if not raw:
        raise typer.Exit(code=1)
    sb = Storyboard.model_validate(raw)
    console.print(
        f"[green]✓ {len(sb.shots)} shots, total ~{sb.total_duration()}s "
        f"(target {sb.target_duration_s}s)[/]"
    )
    cast_data = cast_mod.load(project_id)
    known = {c["name"] for c in cast_data["characters"]}
    bad = []
    for s in sb.shots:
        for ch in s.characters:
            if ch not in known:
                bad.append((s.id, ch))
    if bad:
        console.print("[red]Unknown characters:[/]")
        for sid, ch in bad:
            console.print(f"  {sid} → {ch}")
        raise typer.Exit(code=2)


@sb_app.command("show")
def sb_show(project_id: str = typer.Option(..., "--project", "-p")):
    raw = state.read_json(project_id, "storyboard.json")
    if not raw:
        raise typer.Exit(code=1)
    sb = Storyboard.model_validate(raw)
    table = Table(title=sb.title)
    table.add_column("ID"); table.add_column("Scene"); table.add_column("Dur")
    table.add_column("Model"); table.add_column("Cast"); table.add_column("Prompt(60)")
    for s in sb.shots:
        table.add_row(
            s.id, s.scene, f"{s.duration}s",
            s.model.replace("wan2.7-", ""),
            ",".join(s.characters) or "—",
            (s.prompt[:60] + "…") if len(s.prompt) > 60 else s.prompt,
        )
    console.print(table)


# ---------- render ------------------------------------------------------------
@app.command("render")
def render_cmd(
    project_id: str = typer.Option(..., "--project", "-p"),
    shot_id: str | None = typer.Option(None, "--shot", help="render only this shot"),
    force: bool = typer.Option(False, "--force", help="ignore cache, re-render"),
):
    """Render shots into MP4 clips."""
    raw = state.read_json(project_id, "storyboard.json")
    if not raw:
        console.print("[red]storyboard.json missing — run /storyboard or write it manually first.[/]")
        raise typer.Exit(code=1)
    sb = Storyboard.model_validate(raw)

    if shot_id:
        sb = Storyboard(
            project_id=sb.project_id,
            title=sb.title,
            synopsis=sb.synopsis,
            target_duration_s=sb.target_duration_s,
            resolution=sb.resolution,
            ratio=sb.ratio,
            shots=[s for s in sb.shots if s.id == shot_id],
        )
        if not sb.shots:
            console.print(f"[red]shot {shot_id} not found[/]")
            raise typer.Exit(code=1)

    out = render_mod.render_all(project_id, sb, only_missing=not force)
    typer.echo(json.dumps(out, ensure_ascii=False, indent=2))


# ---------- stitch ------------------------------------------------------------
@app.command("stitch")
def stitch_cmd(
    project_id: str = typer.Option(..., "--project", "-p"),
    crossfade: float = typer.Option(0.0, "--crossfade", help="crossfade seconds (0 = hard cut)"),
):
    """Concat all rendered clips into final/<project>.mp4"""
    raw = state.read_json(project_id, "storyboard.json")
    sb = Storyboard.model_validate(raw)
    pdir = state.project_dir(project_id)
    clips: list[Path] = []
    for s in sb.shots:
        p = pdir / "clips" / f"{s.id}.mp4"
        if not p.exists():
            console.print(f"[yellow]missing {s.id}.mp4 — run `videogen render` first[/]")
            raise typer.Exit(code=1)
        clips.append(p)
    out = pdir / "final" / f"{project_id}.mp4"
    ff.concat(clips, out, crossfade_s=crossfade)
    console.print(f"[green]✓ final video → {out}[/]")


# ---------- task --------------------------------------------------------------
task_app = typer.Typer(help="Inspect/manage Wan tasks directly")
app.add_typer(task_app, name="task")


@task_app.command("query")
def task_query(task_id: str):
    typer.echo(json.dumps(wan.query(task_id), ensure_ascii=False, indent=2))


@task_app.command("wait")
def task_wait(task_id: str, interval: int = 15):
    typer.echo(json.dumps(wan.wait(task_id, interval=interval), ensure_ascii=False, indent=2))


# ---------- doctor ------------------------------------------------------------
@app.command("doctor")
def doctor():
    """Check env, ffmpeg, API connectivity."""
    ok = True
    if not SETTINGS.api_key:
        console.print("[red]✗ DASHSCOPE_API_KEY not set[/]"); ok = False
    else:
        console.print("[green]✓ DASHSCOPE_API_KEY set[/]")
    import shutil as sh
    if sh.which("ffmpeg"):
        console.print("[green]✓ ffmpeg found[/]")
    else:
        console.print("[red]✗ ffmpeg missing — `brew install ffmpeg`[/]"); ok = False
    console.print(f"region: {SETTINGS.region}  base: {SETTINGS.base_url}")
    console.print(f"projects dir: {SETTINGS.projects_dir}")
    raise typer.Exit(code=0 if ok else 1)


if __name__ == "__main__":
    app()
