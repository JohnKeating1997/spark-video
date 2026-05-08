"""videogen — main Typer CLI.

Designed to be driven by Claude Code / Qwen Code via Skill + Slash Commands.
Every command produces JSON-friendly output for agent consumption.

Filesystem model:

  projects/<project_id>/                  ← project tier (lore + shared cast)
      lore.md
      cast/<character_name>/{cast.md,*.png,*.mp3}
      <episode>/                           ← episode tier (one folder per episode)
          script.md
          storyboard.json
          cast.json                        ← built per episode
          cast/<name>/{cast.md,*.png}      ← episode-only NPCs
          cast_built/  clips/  frames/  final/  logs/

`--project / -p` selects the project. `--episode / -e` selects the episode
(accepts ``001`` or ``episode-001``). Lore commands stay project-level.
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
    review as review_mod,
    scene as scene_mod,
    soul as soul_mod,
    state,
    wan,
)
from .config import SETTINGS
from .storyboard import Storyboard

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
cast_app = typer.Typer(help="Manage characters (folder-per-character)")
app.add_typer(cast_app, name="cast")


@cast_app.command("init")
def cast_init(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e", help="episode id, e.g. 001 or episode-001"),
    no_upload: bool = typer.Option(False, "--no-upload", help="skip OSS upload (dry run)"),
):
    """Scan project + episode cast folders, build composites, upload, write cast.json.

    Two tiers (episode overrides project):
      • projects/<id>/cast/<name>/             ← shared across episodes
      • projects/<id>/<episode>/cast/<name>/   ← episode-only NPCs

    Each character lives in its own folder. Composites (multi-pane grids,
    multi-take voice mixes) are only ever built within a single character's
    folder — never across characters.
    """
    payload = cast_mod.init_episode(project_id, episode_id, do_upload=not no_upload)
    table = Table(title=f"Cast for {project_id}/{payload['episode_id']}")
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
        src = c.get("source", "project")
        table.add_row(
            c["name"],
            c.get("id", "?"),
            f"[bold magenta]{src}[/]" if src == "episode" else src,
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
            f"`./bin/videogen cast soul template --name <NAME> --project {project_id}` "
            f"to scaffold one."
        )


@cast_app.command("ls")
def cast_ls(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
):
    data = cast_mod.load(project_id, episode_id)
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


# ---------- cast soul ---------------------------------------------------------
soul_app = typer.Typer(help="Inspect and scaffold soul cards (人设档案)")
cast_app.add_typer(soul_app, name="soul")


@soul_app.command("show")
def soul_show(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
    name: str | None = typer.Option(None, "--name", help="single character; omit for all"),
    fmt: str = typer.Option("text", "--format", help="text | json"),
):
    """Print character souls in a format the director Skill can paste into prompts."""
    data = cast_mod.load(project_id, episode_id)
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
    name: str = typer.Option(..., "--name", help="character display name, e.g. 钱夫人"),
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str | None = typer.Option(
        None, "--episode", "-e",
        help="if set, scaffold under projects/<id>/<episode>/cast/<name>/cast.md (episode-only NPC)",
    ),
    overwrite: bool = typer.Option(False, "--force"),
):
    """Scaffold ``<cast_dir>/<name>/cast.md`` with a fillable template.

    Writes to the episode cast tier when ``--episode`` is given, otherwise
    to the project (shared) cast tier.
    """
    if episode_id:
        cast_root = cast_mod.episode_cast_dir(project_id, episode_id)
    else:
        cast_root = cast_mod.project_cast_dir(project_id)
    char_dir = cast_root / name
    char_dir.mkdir(parents=True, exist_ok=True)
    out = char_dir / cast_mod.SOUL_FILENAME
    if out.exists() and not overwrite:
        console.print(f"[red]{out} exists; use --force to overwrite[/]"); raise typer.Exit(1)
    out.write_text(_SOUL_TEMPLATE.format(name=name), encoding="utf-8")
    console.print(f"[green]✓ wrote {out}[/]")
    console.print(
        f"  drop a portrait into {char_dir}/, then re-run "
        f"`./bin/videogen cast init --project {project_id} "
        f"--episode {episode_id or '<EPISODE>'}`."
    )


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
    episode_id: str | None = typer.Option(
        None, "--episode", "-e",
        help="save into the episode's cast/ folder (NPC unique to this episode). "
             "Omit to save into the project's shared cast/.",
    ),
    name: str = typer.Option(..., "--name", help="NPC display name, e.g. 少林方丈"),
    description: str = typer.Option(
        ..., "--desc",
        help="Appearance description for portrait generation (age, clothing, features)",
    ),
    mood_anchor: str = typer.Option("", "--mood", help="project mood_anchor for style consistency"),
):
    """Generate a portrait for an NPC and save into a per-character cast folder.

    Use this when the storyboard references characters who have dialog or are
    individually named but don't yet have a cast entry (portrait). Without a
    reference_image, the video model will generate inconsistent appearances.
    """
    out = npc_mod.generate_portrait(
        name, description,
        project_id=project_id,
        episode_id=episode_id,
        mood_anchor=mood_anchor,
    )
    console.print(f"[green]✓ NPC portrait → {out}[/]")
    if episode_id:
        console.print(
            f"[dim]Run `./bin/videogen cast init --project {project_id} "
            f"--episode {episode_id}` to include this NPC in cast.json.[/]"
        )
    else:
        console.print(
            f"[dim]Run `./bin/videogen cast init --project {project_id} "
            f"--episode <EPISODE>` to pick this NPC up.[/]"
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


# ---------- episode -----------------------------------------------------------
episode_app = typer.Typer(help="Manage episode folders within a project")
app.add_typer(episode_app, name="episode")


@episode_app.command("ls")
def episode_ls(project_id: str = typer.Option(..., "--project", "-p")):
    """List existing episode folders for a project."""
    eps = state.list_episodes(project_id)
    if not eps:
        console.print(f"[yellow](no episodes in projects/{project_id})[/]")
        raise typer.Exit(code=2)
    for ep in eps:
        console.print(f"  • {ep}")


@episode_app.command("init")
def episode_init(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
):
    """Create projects/<id>/<episode>/ scaffold (clips/frames/final/logs/cast/)."""
    edir = state.episode_dir(project_id, episode_id)
    (edir / "cast").mkdir(exist_ok=True)
    console.print(f"[green]✓ episode dir → {edir}[/]")


# ---------- storyboard --------------------------------------------------------
sb_app = typer.Typer(help="Storyboard validation/inspection")
app.add_typer(sb_app, name="storyboard")


@sb_app.command("validate")
def sb_validate(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
):
    """Validate ./projects/<id>/<episode>/storyboard.json against the schema."""
    raw = state.read_json(project_id, "storyboard.json", episode_id=episode_id)
    if not raw:
        _bail(
            f"storyboard.json missing for {project_id}/"
            f"{state.normalize_episode_id(episode_id)}"
        )
    sb = Storyboard.model_validate(raw)
    console.print(
        f"[green]✓ {len(sb.shots)} shots, total ~{sb.total_duration()}s "
        f"(target {sb.target_duration_s}s)[/]"
    )
    try:
        cast_data = cast_mod.load(project_id, episode_id)
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
    episode_id: str = typer.Option(..., "--episode", "-e"),
    json_out: bool = typer.Option(False, "--json", help="emit machine-readable JSON for the agent"),
):
    """Print duration / shot count / wall-clock estimate. Emits exit code 2 if total
    exceeds VIDEOGEN_LONG_CONFIRM_S so the agent knows to ask the user."""
    raw = state.read_json(project_id, "storyboard.json", episode_id=episode_id)
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
        "episode_id": state.normalize_episode_id(episode_id),
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
        table.add_row("episode", payload["episode_id"])
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
def sb_show(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
):
    raw = state.read_json(project_id, "storyboard.json", episode_id=episode_id)
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
    table.add_column("Model"); table.add_column("Cast")
    table.add_column("Purpose(40)"); table.add_column("Prompt(50)")
    table.add_column("Anchor")
    anchor = (lore.front.mood_anchor if lore else None) or ""
    for s in sb.shots:
        anchor_hit = "✓" if (anchor and anchor in s.prompt) else ("—" if anchor else " ")
        np = s.narrative_purpose or ""
        np_cell = (np[:40] + "…") if len(np) > 40 else (np or "[red]—[/]")
        table.add_row(
            s.id, s.scene, f"{s.duration}s",
            s.model.replace("wan2.7-", ""),
            ",".join(s.characters) or "—",
            np_cell,
            (s.prompt[:50] + "…") if len(s.prompt) > 50 else s.prompt,
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
    no_purpose = [s.id for s in sb.shots if not s.narrative_purpose]
    if no_purpose:
        console.print(
            f"[yellow]·[/] {len(no_purpose)}/{len(sb.shots)} shots missing narrative_purpose: "
            f"{', '.join(no_purpose[:6])}{'…' if len(no_purpose) > 6 else ''}"
        )


# ---------- scene -------------------------------------------------------------
scene_app = typer.Typer(help="Per-scene screenplay/storyboard fragments (parallel pipeline)")
app.add_typer(scene_app, name="scene")


@scene_app.command("scaffold")
def scene_scaffold(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
    num: int = typer.Option(..., "--num", "-n", help="scene number (1, 2, 3, ...)"),
    force: bool = typer.Option(False, "--force"),
):
    """Create empty scenes/scene-NN.md template for the screenwriter."""
    out = scene_mod.scaffold_scene(project_id, episode_id, num, force=force)
    if out.exists() and not force:
        # scaffold_scene returns the path either way; figure out if we wrote.
        pass
    console.print(f"[green]✓ scene template → {out}[/]")
    console.print(
        f"  fill it in, then signal ready: "
        f"[bold]./bin/videogen scene ready --project {project_id} "
        f"--episode {episode_id} --num {num}[/]"
    )


@scene_app.command("ready")
def scene_ready_cmd(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
    num: int = typer.Option(..., "--num", "-n"),
):
    """Touch scenes/scene-NN.ready — sentinel that director can pick up scene NN."""
    try:
        sentinel = scene_mod.mark_scene_ready(project_id, episode_id, num)
    except FileNotFoundError as e:
        _bail(str(e))
    console.print(f"[green]✓ ready → {sentinel.name}[/]")


@scene_app.command("status")
def scene_status_cmd(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Show per-scene progress (md / ready / json)."""
    payload = scene_mod.status(project_id, episode_id)
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    table = Table(title=f"scenes · {payload['episode_id']}")
    table.add_column("scene")
    table.add_column("script (.md)")
    table.add_column("ready")
    table.add_column("storyboard (.json)")
    if not payload["scenes"]:
        console.print("[yellow](no scenes/ files yet)[/]")
        return
    for s in payload["scenes"]:
        table.add_row(
            f"scene-{s['num']:02d}",
            "✓" if s["md"] else "—",
            "✓" if s["ready"] else "—",
            "✓" if s["json"] else "—",
        )
    console.print(table)


@scene_app.command("compile")
def scene_compile_cmd(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
    title: str | None = typer.Option(None, "--title"),
    synopsis: str | None = typer.Option(None, "--synopsis"),
    target: int | None = typer.Option(None, "--target", help="target duration in seconds"),
):
    """Merge scenes/scene-*.md → script.md and scenes/scene-*.json → storyboard.json."""
    try:
        result = scene_mod.compile_episode(
            project_id, episode_id,
            title=title, synopsis=synopsis, target_duration_s=target,
        )
    except (FileNotFoundError, ValueError) as e:
        _bail(str(e))
    console.print(
        f"[green]✓ {result.scenes} scenes / {result.shots} shots / "
        f"~{result.total_duration_s}s total[/]"
    )
    console.print(f"  script     → {result.script_path}")
    console.print(f"  storyboard → {result.storyboard_path}")
    if result.warnings:
        console.print("[yellow]continuity warnings (won't block render):[/]")
        for w in result.warnings:
            console.print(f"  ⚠ {w}")


# ---------- render ------------------------------------------------------------
@app.command("render")
def render_cmd(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
    shot_id: str | None = typer.Option(None, "--shot", help="render only this shot"),
    force: bool = typer.Option(False, "--force", help="ignore cache, re-render"),
    yes: bool = typer.Option(False, "--yes", "-y", help="skip the over-budget confirmation gate"),
    review: bool = typer.Option(True, "--review/--no-review", help="qwen3-vl-plus per-clip review (default on)"),
    score_threshold: float | None = typer.Option(None, "--score-threshold", help="ACCEPT if score >= threshold (default from .env)"),
    max_retry: int | None = typer.Option(None, "--max-retry", help="max attempts per shot (default 3 from .env)"),
    auto_rewrite: bool = typer.Option(True, "--auto-rewrite/--no-auto-rewrite", help="qwen-text auto rewrite between retries"),
    concurrency: int | None = typer.Option(None, "--concurrency", help="max parallel chain groups"),
    reset_attempts: bool = typer.Option(False, "--reset-attempts", help="wipe prior attempts for the targeted shot(s)"),
):
    """Render shots into MP4 clips, in parallel by chain group, with per-clip review.

    Exit codes:
      0  all shots passed (or were cached)
      1  invalid args / missing storyboard
      2  over-budget; re-run with --yes
      3  one or more shots flagged for director rewrite (escalation needed)
    """
    raw = state.read_json(project_id, "storyboard.json", episode_id=episode_id)
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

    cfg = render_mod.RenderConfig.from_settings(
        do_review=review,
        threshold=score_threshold,
        max_retry=max_retry,
        do_auto_rewrite=auto_rewrite,
    )

    try:
        out = render_mod.render_all(
            project_id, episode_id, sb,
            only_missing=not force,
            cfg=cfg,
            concurrency=concurrency,
            shot_ids=[shot_id] if shot_id else None,
            reset=reset_attempts,
        )
    except FileNotFoundError as e:
        _bail(str(e))

    typer.echo(json.dumps(out, ensure_ascii=False, indent=2))

    # Exit 3 if any targeted shot needs director rewrite.
    targeted = {shot_id} if shot_id else None
    needs = [
        sid for sid, rec in out.items()
        if rec.get("needs_director_rewrite")
        and (targeted is None or sid in targeted)
    ]
    if needs:
        console.print(
            f"[red]exit 3: {len(needs)} shot(s) need director rewrite: "
            f"{', '.join(needs[:6])}{'…' if len(needs) > 6 else ''}[/]"
        )
        raise typer.Exit(code=3)


@app.command("render-graph")
def render_graph_cmd(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Show how the storyboard slices into parallel chain groups."""
    raw = state.read_json(project_id, "storyboard.json", episode_id=episode_id)
    if not raw:
        _bail("storyboard.json missing")
    sb = Storyboard.model_validate(raw)
    groups = render_mod.slice_chain_groups(sb.shots)
    if json_out:
        payload = [
            {"index": g.index, "label": g.label(),
             "shots": [s.id for s in g.shots],
             "duration_s": sum(s.duration for s in g.shots)}
            for g in groups
        ]
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    table = Table(title=f"Chain DAG · {len(groups)} groups (concurrency cap = {SETTINGS.max_concurrency})")
    table.add_column("group"); table.add_column("shots"); table.add_column("dur")
    for g in groups:
        table.add_row(
            f"#{g.index}",
            " → ".join(s.id for s in g.shots),
            f"{sum(s.duration for s in g.shots)}s",
        )
    console.print(table)
    console.print(
        f"[dim]每个 group 内串行(链帧依赖), groups 之间 ThreadPoolExecutor 并发. "
        f"想增加并行度: 把更多 shot 的 use_prev_last_frame_as_first 改为 false。[/]"
    )


# ---------- review ------------------------------------------------------------
@app.command("review")
def review_cmd(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
    shot_id: str = typer.Option(..., "--shot", help="shot id, e.g. S01-002"),
    version: int | None = typer.Option(None, "--ver", help="attempt version (default: latest)"),
    threshold: float | None = typer.Option(None, "--score-threshold"),
):
    """Re-run qwen3-vl-plus review on a previously rendered clip."""
    raw = state.read_json(project_id, "storyboard.json", episode_id=episode_id)
    if not raw:
        _bail("storyboard.json missing")
    sb = Storyboard.model_validate(raw)
    shot = next((s for s in sb.shots if s.id == shot_id), None)
    if not shot:
        _bail(f"shot {shot_id} not in storyboard")

    shots_state = render_mod.load_shots_state(project_id, episode_id)
    rec = shots_state.get(shot_id)
    if not rec or not rec.get("attempts"):
        _bail(f"no attempts on disk for {shot_id}; render it first")

    if version is None:
        attempt = rec["attempts"][-1]
    else:
        attempt = next((a for a in rec["attempts"] if a.get("version") == version), None)
        if not attempt:
            _bail(f"no attempt ver{version} for {shot_id}")
    if attempt.get("status") != "SUCCEEDED":
        _bail(f"attempt ver{attempt.get('version')} did not succeed; nothing to review")
    if not attempt.get("video_url"):
        _bail("attempt has no video_url; cannot fetch the clip for review")

    scene = sb.scene_map().get(shot.scene)
    lore = lore_mod.load(project_id, projects_dir=SETTINGS.projects_dir)
    review = review_mod.review_clip(
        attempt["video_url"], shot=shot, scene=scene, lore=lore,
        threshold=threshold,
    )
    typer.echo(json.dumps(review, ensure_ascii=False, indent=2))


# ---------- stitch ------------------------------------------------------------
@app.command("stitch")
def stitch_cmd(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
    crossfade: float = typer.Option(0.0, "--crossfade", help="crossfade seconds (0 = hard cut)"),
    allow_below_threshold: bool = typer.Option(
        False, "--allow-below-threshold",
        help="stitch even if some shots are flagged needs_director_rewrite (use best-of-N)",
    ),
):
    """Concat winner clip per shot into final/<project>-<episode>.mp4

    Reads `shots_state.json[shot].winner_path` to pick the winning version.
    Shots flagged `needs_director_rewrite` block stitch unless
    `--allow-below-threshold` is passed.
    """
    raw = state.read_json(project_id, "storyboard.json", episode_id=episode_id)
    if not raw:
        _bail("storyboard.json missing")
    sb = Storyboard.model_validate(raw)
    edir = state.episode_dir(project_id, episode_id)
    ep_norm = state.normalize_episode_id(episode_id)

    shots_state = render_mod.load_shots_state(project_id, episode_id)
    clips: list[Path] = []
    flagged: list[str] = []
    missing: list[str] = []
    summary: list[tuple[str, int | None, str]] = []

    for s in sb.shots:
        rec = shots_state.get(s.id) or {}
        winner_path_str = rec.get("winner_path")
        winner_clip = Path(winner_path_str) if winner_path_str else (edir / "clips" / f"{s.id}.mp4")
        if not winner_clip.exists():
            missing.append(s.id)
            continue
        if rec.get("needs_director_rewrite"):
            flagged.append(s.id)
        clips.append(winner_clip)
        summary.append((s.id, rec.get("winner_version"), winner_clip.name))

    if missing:
        console.print(
            f"[red]missing winner clip(s):[/] {', '.join(missing)}\n"
            f"  run `./bin/videogen render --project {project_id} --episode {episode_id}` first."
        )
        raise typer.Exit(code=1)

    if flagged and not allow_below_threshold:
        console.print(
            f"[red]{len(flagged)} shot(s) flagged needs_director_rewrite:[/] "
            f"{', '.join(flagged[:6])}{'…' if len(flagged) > 6 else ''}\n"
            f"  fix them first OR re-run stitch with --allow-below-threshold to ship best-of-N."
        )
        raise typer.Exit(code=3)

    out = edir / "final" / f"{project_id}-{ep_norm}.mp4"
    ff.concat(clips, out, crossfade_s=crossfade)
    console.print(f"[green]✓ final video → {out}[/]")

    # Time-coded shot map for the GATE 4 review.
    table = Table(title=f"shot map · {out.name}")
    table.add_column("shot"); table.add_column("ver"); table.add_column("file"); table.add_column("flag")
    for sid, ver, name in summary:
        table.add_row(
            sid,
            f"ver{ver}" if ver else "—",
            name,
            "[red]rewrite[/]" if sid in set(flagged) else "",
        )
    console.print(table)


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
