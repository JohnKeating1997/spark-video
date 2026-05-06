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

from . import (
    cast as cast_mod,
    ffmpeg as ff,
    lore as lore_mod,
    npc as npc_mod,
    render as render_mod,
    soul as soul_mod,
    state,
    wan,
)
from .config import SETTINGS
from .storyboard import Scene, Shot, Storyboard

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    pretty_exceptions_short=True,
    help="Long-form AI video generator (Wan2.7) — driven by Claude Code Skills.",
)
console = Console()


def _bail(msg: str, code: int = 1) -> None:
    console.print(f"[red]✗[/] {msg}")
    raise typer.Exit(code=code)

# ---------- cast --------------------------------------------------------------
cast_app = typer.Typer(help="Manage characters in ./cast")
app.add_typer(cast_app, name="cast")


@cast_app.command("init")
def cast_init(
    project_id: str = typer.Option(..., "--project", "-p"),
    cast_dir: Path = typer.Option(Path("./cast"), "--dir"),
    no_upload: bool = typer.Option(False, "--no-upload", help="skip OSS upload (dry run)"),
):
    """Scan cast/ directories (project + global), build composites, upload, write cast.json.

    Looks in two places (project tier overrides global tier):
      • projects/<id>/cast/   ← project-specific characters
      • ./cast/  (or --dir)   ← global pool
    """
    payload = cast_mod.init_project(project_id, cast_dir, do_upload=not no_upload)
    table = Table(title=f"Cast for {project_id}")
    table.add_column("Name")
    table.add_column("Id")
    table.add_column("Source")
    table.add_column("Image")
    table.add_column("Voice")
    table.add_column("Soul")
    table.add_column("Uploaded")
    for c in payload["characters"]:
        n_img = len(c.get("images_local", []))
        n_aud = len(c.get("audios_local", []))
        img_cell = Path(c["image_local"]).name + (f" (×{n_img}→grid)" if c.get("composite_image") else "")
        if c.get("audio_local"):
            voice_cell = Path(c["audio_local"]).name + (f" (×{n_aud}→mix)" if c.get("composite_audio") else "")
        else:
            voice_cell = "—"
        src = c.get("source", "global")
        table.add_row(
            c["name"],
            c.get("id", "?"),
            f"[bold magenta]{src}[/]" if src == "project" else src,
            img_cell,
            voice_cell,
            "✓" if c.get("soul") else "—",
            "✓" if c.get("image_url") else "—",
        )
    console.print(table)
    missing_soul = [c["name"] for c in payload["characters"] if not c.get("soul")]
    if missing_soul:
        console.print(
            f"[yellow]Tip:[/] {len(missing_soul)} character(s) without a soul card "
            f"({', '.join(missing_soul)}). Run "
            f"`./bin/videogen cast soul template --name <NAME>` to scaffold one."
        )


@cast_app.command("ls")
def cast_ls(project_id: str = typer.Option(..., "--project", "-p")):
    data = cast_mod.load(project_id)
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


# ---------- cast soul ---------------------------------------------------------
soul_app = typer.Typer(help="Inspect and scaffold soul cards (人设档案)")
cast_app.add_typer(soul_app, name="soul")


@soul_app.command("show")
def soul_show(
    project_id: str = typer.Option(..., "--project", "-p"),
    name: str | None = typer.Option(None, "--name", help="single character; omit for all"),
    fmt: str = typer.Option("text", "--format", help="text | json"),
):
    """Print character souls in a format the director Skill can paste into prompts."""
    data = cast_mod.load(project_id)
    chars = [c for c in data["characters"] if (name is None or c["name"] == name)]
    if not chars:
        console.print(f"[red]no character matched[/]"); raise typer.Exit(1)

    if fmt == "json":
        typer.echo(json.dumps([{"name": c["name"], "soul": c.get("soul")} for c in chars],
                              ensure_ascii=False, indent=2))
        return

    for c in chars:
        console.print(f"[bold cyan]## {c['name']}[/]")
        if not c.get("soul"):
            console.print("  (no soul card)\n"); continue
        s = soul_mod.Soul(
            path=c["soul"]["path"],
            front=soul_mod.SoulFront.model_validate(c["soul"]["front"]),
            body=c["soul"].get("body", ""),
        )
        console.print(soul_mod.render_for_prompt(s))
        console.print("")


@soul_app.command("template")
def soul_template(
    name: str = typer.Option(..., "--name", help="character stem, e.g. 钱夫人"),
    project_id: str | None = typer.Option(
        None, "--project", "-p",
        help="if set, write to projects/<id>/cast/<name>.md (project-level)",
    ),
    cast_dir: Path | None = typer.Option(
        None, "--dir",
        help="explicit cast dir; default = ./cast (global) or projects/<id>/cast (when --project given)",
    ),
    overwrite: bool = typer.Option(False, "--force"),
):
    """Scaffold a soul-card template (project-level if --project given, else global)."""
    if cast_dir is None:
        if project_id:
            cast_dir = SETTINGS.projects_dir / project_id / "cast"
        else:
            cast_dir = Path("./cast")
    cast_dir.mkdir(parents=True, exist_ok=True)
    out = cast_dir / f"{name}.md"
    if out.exists() and not overwrite:
        console.print(f"[red]{out} exists; use --force to overwrite[/]"); raise typer.Exit(1)
    out.write_text(_SOUL_TEMPLATE.format(name=name), encoding="utf-8")
    console.print(f"[green]✓ wrote {out}[/]\nedit it, then re-run `./bin/videogen cast init`.")


_SOUL_TEMPLATE = """\
---
# Soul card for {name}. Fields are optional — leave them blank or remove
# the line if you don't want to commit to a value yet. The director Skill
# pulls action verbs, dialog, and dynamics from whatever you DO fill in.
name: {name}
# id: ascii_slug   ← optional. ASCII-only filename used for OSS uploads.
#                    If omitted, derived from `name` (or hashed if name is
#                    not ASCII-safe). Recommended for non-ASCII display names.
aliases: []
# age: 35
# gender: female
# occupation: 同福客栈掌柜
# archetype: 古道热肠的小老板娘 / 笑点担当
# voice_style: 嗓门洪亮, 拖长音, 喜欢用反问
catchphrases: []
mannerisms: []
relationships: []
# example:
# relationships:
#   - target: 钱夫人
#     type: 死对头
#     backstory: 三年前因为一坛酱菜结下梁子, 见面就互怼
do: []
dont: []
---

# 人物小传

(自由发挥, 几句话讲清这个人是谁、来自哪、有什么伤疤或目标。LLM 写剧本时会读这段。)

## 口吻范例

> "..."

## 表演要点

- 进场:
- 情绪峰值:
- 离场:
"""


@cast_app.command("generate-npc")
def cast_generate_npc(
    project_id: str = typer.Option(..., "--project", "-p"),
    name: str = typer.Option(..., "--name", help="NPC display name, e.g. 少林方丈"),
    description: str = typer.Option(
        ..., "--desc",
        help="Appearance description for portrait generation (age, clothing, features)",
    ),
    mood_anchor: str = typer.Option("", "--mood", help="project mood_anchor for style consistency"),
):
    """Generate a portrait for an NPC using text-to-image, save to project cast/.

    Use this when the storyboard references characters who have dialog or are
    individually named but don't yet have a cast entry (portrait). Without a
    reference_image, the video model will generate inconsistent appearances.
    """
    out = npc_mod.generate_portrait(
        name, description, project_id=project_id, mood_anchor=mood_anchor,
    )
    console.print(f"[green]✓ NPC portrait → {out}[/]")
    console.print(
        f"[dim]Run `./bin/videogen cast init --project {project_id}` to include "
        f"this NPC in cast.json.[/]"
    )


# ---------- lore --------------------------------------------------------------
lore_app = typer.Typer(help="Manage per-project story bible (lore.md)")
app.add_typer(lore_app, name="lore")


@lore_app.command("template")
def lore_template(
    project_id: str = typer.Option(..., "--project", "-p"),
    title: str = typer.Option("Untitled", "--title", help="display title for the story"),
    overwrite: bool = typer.Option(False, "--force"),
):
    """Scaffold projects/<id>/lore.md with a fillable template."""
    pdir = state.project_dir(project_id)
    out = pdir / lore_mod.LORE_FILENAME
    if out.exists() and not overwrite:
        console.print(f"[red]{out} exists; use --force to overwrite[/]"); raise typer.Exit(1)
    out.write_text(lore_mod.LORE_TEMPLATE.format(title=title), encoding="utf-8")
    console.print(f"[green]✓ wrote {out}[/]\nedit it, then run `./bin/videogen lore show --project {project_id}`.")


@lore_app.command("show")
def lore_show(
    project_id: str = typer.Option(..., "--project", "-p"),
    fmt: str = typer.Option("text", "--format", help="text | json"),
):
    """Render the project's lore in the same format the director Skill consumes."""
    lore = lore_mod.load(project_id, projects_dir=SETTINGS.projects_dir)
    if not lore:
        console.print("[yellow](no lore.md for this project)[/]")
        console.print(f"  scaffold one with: ./bin/videogen lore template --project {project_id}")
        raise typer.Exit(code=2)
    if fmt == "json":
        typer.echo(json.dumps(lore.to_dict(), ensure_ascii=False, indent=2))
        return
    console.print(lore_mod.render_for_prompt(lore))


@lore_app.command("validate")
def lore_validate(project_id: str = typer.Option(..., "--project", "-p")):
    """Parse projects/<id>/lore.md and surface schema errors loudly."""
    lore = lore_mod.load(project_id, projects_dir=SETTINGS.projects_dir)
    if not lore:
        console.print(f"[red]projects/{project_id}/lore.md missing[/]"); raise typer.Exit(1)
    f = lore.front
    warnings: list[str] = []
    if not f.mood_anchor:
        warnings.append("mood_anchor is empty — without it, every shot prompt drifts visually.")
    if not f.title:
        warnings.append("title is empty.")
    for w in warnings:
        console.print(f"[yellow]·[/] {w}")
    console.print(f"[green]✓ lore.md parses cleanly[/]")


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
    try:
        cast_data = cast_mod.load(project_id)
    except FileNotFoundError as e:
        _bail(str(e))
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

    warnings = sb.lint()
    if warnings:
        console.print("[yellow]continuity warnings (won't block render):[/]")
        for w in warnings:
            console.print(f"  ⚠ {w}")
        console.print(
            "[dim]see .claude/skills/video-director/SKILL.md → "
            "'续接黄金五条' for fixes.[/]"
        )


@sb_app.command("estimate")
def sb_estimate(
    project_id: str = typer.Option(..., "--project", "-p"),
    json_out: bool = typer.Option(False, "--json", help="emit machine-readable JSON for the agent"),
):
    """Print duration / shot count / wall-clock estimate. Emits exit code 2 if total
    exceeds VIDEOGEN_LONG_CONFIRM_S so the agent knows to ask the user."""
    raw = state.read_json(project_id, "storyboard.json")
    if not raw:
        console.print("[red]storyboard.json missing[/]")
        raise typer.Exit(code=1)
    sb = Storyboard.model_validate(raw)

    total_s = sb.total_duration()
    n_shots = len(sb.shots)
    wall_min = sb.estimated_wall_clock_min()
    threshold = SETTINGS.long_confirm_s
    over_budget = total_s > threshold

    by_model: dict[str, int] = {}
    for s in sb.shots:
        by_model[s.model] = by_model.get(s.model, 0) + s.duration

    payload = {
        "project_id": project_id,
        "shots": n_shots,
        "total_duration_s": total_s,
        "target_duration_s": sb.target_duration_s,
        "wall_clock_min_estimate": round(wall_min, 1),
        "resolution": sb.resolution,
        "ratio": sb.ratio,
        "duration_by_model_s": by_model,
        "long_confirm_threshold_s": threshold,
        "over_budget": over_budget,
        "advice": (
            f"Total {total_s}s exceeds the {threshold}s confirmation threshold — "
            "ask the user to approve before rendering."
        ) if over_budget else "Within the confirmation threshold; safe to render.",
    }

    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        table = Table(title=f"Estimate · {sb.title}")
        table.add_column("metric"); table.add_column("value")
        table.add_row("shots", str(n_shots))
        table.add_row("total duration", f"{total_s}s ({total_s/60:.1f} min)")
        table.add_row("target", f"{sb.target_duration_s}s")
        table.add_row("wall-clock estimate", f"~{wall_min:.0f} min (sequential, 1–5 min/shot)")
        table.add_row("resolution / ratio", f"{sb.resolution} / {sb.ratio}")
        table.add_row("duration by model",
                     ", ".join(f"{m.replace('wan2.7-','')}: {d}s" for m, d in by_model.items()))
        table.add_row("budget threshold", f"{threshold}s")
        table.add_row(
            "verdict",
            "[red]OVER BUDGET — confirm with user[/]" if over_budget else "[green]within budget[/]",
        )
        console.print(table)
        console.print(f"\n[bold]{payload['advice']}[/]")

    raise typer.Exit(code=2 if over_budget else 0)


@sb_app.command("show")
def sb_show(project_id: str = typer.Option(..., "--project", "-p")):
    raw = state.read_json(project_id, "storyboard.json")
    if not raw:
        raise typer.Exit(code=1)
    sb = Storyboard.model_validate(raw)

    lore = lore_mod.load(project_id, projects_dir=SETTINGS.projects_dir)
    if lore and lore.front.mood_anchor:
        console.print(f"[dim]世界观风格锚: \"{lore.front.mood_anchor}\"[/]")
    elif not lore:
        console.print(
            f"[yellow]Tip:[/] no lore.md for this project. "
            f"`./bin/videogen lore template --project {project_id}` to add one."
        )

    # Show scene definitions if present
    if sb.scenes:
        scene_table = Table(title="Scenes")
        scene_table.add_column("ID")
        scene_table.add_column("Name")
        scene_table.add_column("Description(80)")
        scene_table.add_column("Characters")
        scene_table.add_column("Seed")
        for sc in sb.scenes:
            scene_table.add_row(
                sc.id, sc.name,
                (sc.description[:80] + "…") if len(sc.description) > 80 else sc.description,
                ",".join(sc.characters_present) or "—",
                str(sc.seed) if sc.seed else "—",
            )
        console.print(scene_table)
        console.print("")

    table = Table(title=sb.title)
    table.add_column("ID"); table.add_column("Scene"); table.add_column("Dur")
    table.add_column("Model"); table.add_column("Cast"); table.add_column("Prompt(60)")
    table.add_column("Anchor")
    anchor = (lore.front.mood_anchor if lore else None) or ""
    for s in sb.shots:
        anchor_hit = "✓" if (anchor and anchor in s.prompt) else ("—" if anchor else " ")
        table.add_row(
            s.id, s.scene, f"{s.duration}s",
            s.model.replace("wan2.7-", ""),
            ",".join(s.characters) or "—",
            (s.prompt[:60] + "…") if len(s.prompt) > 60 else s.prompt,
            anchor_hit,
        )
    console.print(table)
    if anchor:
        misses = [s.id for s in sb.shots if anchor not in s.prompt]
        if misses:
            console.print(
                f"[yellow]·[/] {len(misses)}/{len(sb.shots)} shots missing the mood anchor: "
                f"{', '.join(misses[:6])}{'…' if len(misses) > 6 else ''}"
            )


# ---------- render ------------------------------------------------------------
@app.command("render")
def render_cmd(
    project_id: str = typer.Option(..., "--project", "-p"),
    shot_id: str | None = typer.Option(None, "--shot", help="render only this shot"),
    force: bool = typer.Option(False, "--force", help="ignore cache, re-render"),
    yes: bool = typer.Option(False, "--yes", "-y", help="skip the over-budget confirmation gate"),
):
    """Render shots into MP4 clips."""
    raw = state.read_json(project_id, "storyboard.json")
    if not raw:
        console.print("[red]storyboard.json missing — run /storyboard or write it manually first.[/]")
        raise typer.Exit(code=1)
    sb = Storyboard.model_validate(raw)

    # Budget gate: only when rendering the whole storyboard, not a single shot retry.
    if shot_id is None and not yes:
        total_s = sb.total_duration()
        if total_s > SETTINGS.long_confirm_s:
            console.print(
                f"[yellow]⚠ total {total_s}s ({total_s/60:.1f} min) exceeds the "
                f"{SETTINGS.long_confirm_s}s confirmation threshold.[/]\n"
                f"  shots: {len(sb.shots)}  ·  wall-clock ≈ {sb.estimated_wall_clock_min():.0f} min\n"
                f"  Re-run with [bold]--yes[/] (or have the agent ask the user first)."
            )
            raise typer.Exit(code=2)

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

    try:
        out = render_mod.render_all(project_id, sb, only_missing=not force)
    except FileNotFoundError as e:
        _bail(str(e))
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
