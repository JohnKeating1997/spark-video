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
    bgm as bgm_mod,
    cast as cast_mod,
    ffmpeg as ff,
    lore as lore_mod,
    model_log,
    movie_set as movie_set_mod,
    npc as npc_mod,
    prop as prop_mod,
    render as render_mod,
    review as review_mod,
    scene as scene_mod,
    soul as soul_mod,
    state,
    tts as tts_mod,
)
from .config import SETTINGS
from .providers import get_provider, list_providers
from .storyboard import BGMConfig, Storyboard

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    pretty_exceptions_short=True,
    help="Long-form AI video generator (Wan / HappyHorse) — driven by Claude Code Skills.",
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


@cast_app.command("fork")
def cast_fork(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
    name: str = typer.Option(..., "--name", help="character name in projects/<p>/cast/<NAME>/"),
    overwrite: bool = typer.Option(
        False, "--force",
        help="overwrite the episode-tier folder if it already exists",
    ),
    drop_portraits: bool = typer.Option(
        False, "--drop-portraits",
        help="copy soul card + voice but NOT the portrait images "
             "(use this when you plan to regenerate the portrait with "
             "different clothing via `cast generate-npc`)",
    ),
    regen_desc: str | None = typer.Option(
        None, "--regen",
        help="after copying, regenerate the portrait via wan2.6-t2i with "
             "this appearance description (e.g. for a costume change). "
             "Implies --drop-portraits.",
    ),
    mood_anchor: str = typer.Option(
        "", "--mood",
        help="mood_anchor for portrait regen; default reads from project lore.md",
    ),
):
    """Deep-copy a project-tier cast folder into the episode tier.

    Use this when an episode genuinely needs a costume / appearance
    override that the rest of the project shouldn't see. Workflow:

    \b
      1. ``cast fork --project p --episode e --name 钱夫人``
         → projects/p/e/cast/钱夫人/  (copy of projects/p/cast/钱夫人/)
      2. (Optional) Replace or regenerate the portrait inside the
         episode folder. Either drop a new image manually, or run
         ``cast generate-npc --episode e --name 钱夫人 --desc "..."``
         (overwrites <name>.png inside the episode folder).
      3. ``cast init --project p --episode e``
         → cast.json now uses the episode portrait for this character.

    The ``--regen`` flag bundles steps 1 + 2 + 3 in one call by also
    invoking the t2i NPC pipeline with the new appearance description.
    """
    src = cast_mod.project_cast_dir(project_id) / name
    if not src.is_dir():
        _bail(
            f"projects/{project_id}/cast/{name}/ does not exist. "
            f"Fork only makes sense for existing project-tier cast members."
        )
    dst = cast_mod.episode_cast_dir(project_id, episode_id) / name
    if dst.exists() and not overwrite:
        _bail(
            f"{dst} already exists. Use --force to overwrite, or just "
            f"edit the existing episode-tier folder by hand."
        )
    if dst.exists():
        import shutil as _sh
        _sh.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Copy everything; optionally drop portraits.
    drop_portraits = drop_portraits or (regen_desc is not None)
    import shutil as _sh
    _sh.copytree(src, dst)
    if drop_portraits:
        for p in list(dst.iterdir()):
            if p.suffix.lower() in cast_mod.IMAGE_EXTS:
                p.unlink()
                console.print(f"  [dim]· dropped {p.name}[/]")
    console.print(f"[green]✓ forked → {dst}[/]")

    if regen_desc:
        if not mood_anchor:
            lore = lore_mod.load(project_id, projects_dir=SETTINGS.projects_dir)
            if lore and lore.front.mood_anchor:
                mood_anchor = lore.front.mood_anchor
        out = npc_mod.generate_portrait(
            name, regen_desc,
            project_id=project_id,
            episode_id=episode_id,
            mood_anchor=mood_anchor,
        )
        console.print(f"[green]✓ regenerated portrait → {out}[/]")
    else:
        console.print(
            f"[dim]· next: drop a new portrait into {dst}/, OR run "
            f"`./bin/videogen cast generate-npc --project {project_id} "
            f"--episode {episode_id} --name {name} --desc \"<new appearance>\"`[/]"
        )
    console.print(
        f"[dim]· then run "
        f"`./bin/videogen cast init --project {project_id} --episode {episode_id}` "
        f"to rebuild cast.json with the episode override.[/]"
    )


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


# ---------- movie-set ---------------------------------------------------------
set_app = typer.Typer(
    help="Manage 布景 / movie sets (folder-per-set, two-tier project↔episode)",
)
app.add_typer(set_app, name="set")


@set_app.command("init")
def set_init(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
    no_upload: bool = typer.Option(False, "--no-upload", help="skip OSS upload (dry run)"),
):
    """Scan project + episode movie-set folders, build composites, upload, write movie_set.json.

    Two tiers (episode overrides project) — same model as cast:

      • projects/<id>/movie-set/<name>/             ← shared (e.g. sitcom rooms)
      • projects/<id>/<episode>/movie-set/<name>/   ← episode-only locations

    Each set lives in its own folder. Multi-image sets get a 2/4/9-pane
    grid (composed within ONE set's folder, never across sets).

    A set is *optional* — episodes with no sets simply skip the set
    reference image at render time. Scenes that name a ``set_id`` get
    that set's image appended to every r2v shot's ``media[]``.
    """
    payload = movie_set_mod.init_episode(project_id, episode_id, do_upload=not no_upload)
    sets = payload["sets"]
    if not sets:
        console.print(
            f"[yellow](no movie sets found in {payload['project_set_dir']} "
            f"or {payload['episode_set_dir']})[/]"
        )
        console.print(
            f"  scaffold one with: ./bin/videogen set scaffold --project {project_id} "
            f"--name \"<set name>\""
        )
        return
    table = Table(title=f"Movie sets for {project_id}/{payload['episode_id']}")
    table.add_column("Name")
    table.add_column("Id")
    table.add_column("Source")
    table.add_column("Image")
    table.add_column("Card")
    table.add_column("Uploaded")
    for s in sets:
        n_img = len(s.get("images_local", []))
        img_cell = Path(s["image_local"]).name + (
            f" (×{n_img}→grid)" if s.get("composite_image") else ""
        )
        src = s.get("source", "project")
        table.add_row(
            s["name"],
            s.get("id", "?"),
            f"[bold magenta]{src}[/]" if src == "episode" else src,
            img_cell,
            "✓" if s.get("card") else "—",
            "✓" if s.get("image_url") else "—",
        )
    console.print(table)


@set_app.command("ls")
def set_ls(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
):
    """Print movie_set.json for the episode."""
    typer.echo(json.dumps(
        movie_set_mod.load(project_id, episode_id), ensure_ascii=False, indent=2,
    ))


@set_app.command("scaffold")
def set_scaffold(
    name: str = typer.Option(..., "--name", help="set display name, e.g. 同福客栈大堂"),
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str | None = typer.Option(
        None, "--episode", "-e",
        help="if set, scaffold under projects/<id>/<episode>/movie-set/<name>/ "
             "(episode-only location). Default: project-shared set.",
    ),
    overwrite: bool = typer.Option(False, "--force"),
):
    """Scaffold ``<set_dir>/<name>/set.md`` with a fillable template.

    Defaults to the **project** tier (shared across all episodes —
    perfect for sitcom recurring rooms). Pass ``--episode`` for a
    one-off location that lives only in this episode.
    """
    if episode_id:
        root = movie_set_mod.episode_set_dir(project_id, episode_id)
    else:
        root = movie_set_mod.project_set_dir(project_id)
    set_dir = root / name
    set_dir.mkdir(parents=True, exist_ok=True)
    out = set_dir / movie_set_mod.SET_FILENAME
    if out.exists() and not overwrite:
        console.print(f"[red]{out} exists; use --force to overwrite[/]")
        raise typer.Exit(1)
    out.write_text(movie_set_mod.SET_TEMPLATE.format(name=name), encoding="utf-8")
    console.print(f"[green]✓ wrote {out}[/]")
    console.print(
        f"  drop a reference image into {set_dir}/, then re-run "
        f"`./bin/videogen set init --project {project_id} "
        f"--episode {episode_id or '<EPISODE>'}`."
    )


@set_app.command("generate")
def set_generate(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str | None = typer.Option(
        None, "--episode", "-e",
        help="save into the episode's movie-set/ folder (episode-only). "
             "Omit to save into the project's shared movie-set/.",
    ),
    name: str = typer.Option(..., "--name", help="set display name"),
    description: str = typer.Option(
        ..., "--desc",
        help="Detailed description for portrait generation: 材质 / 布局 / 灯光 / 关键道具",
    ),
    mood_anchor: str = typer.Option(
        "", "--mood",
        help="project mood_anchor for style consistency (default: from lore.md)",
    ),
):
    """Generate a reference image for a set via wan2.6-t2i.

    Useful when you have no on-set reference photo handy and want the
    model to invent a consistent location based on a textual brief.
    Reuses the same t2i pipeline as `cast generate-npc`.
    """
    if not mood_anchor:
        lore = lore_mod.load(project_id, projects_dir=SETTINGS.projects_dir)
        if lore and lore.front.mood_anchor:
            mood_anchor = lore.front.mood_anchor

    if episode_id:
        set_dir = movie_set_mod.episode_set_dir(project_id, episode_id) / name
    else:
        set_dir = movie_set_mod.project_set_dir(project_id) / name
    set_dir.mkdir(parents=True, exist_ok=True)

    # Re-use NPC generation but route the file into the set folder.
    # We do this by pointing the NPC writer's project/episode at the
    # right cast dir... but npc.py hard-codes `cast` paths, so just
    # call the underlying t2i + download helpers directly here.
    prompt = ", ".join(filter(None, [
        f"场景照片, {name}",
        description,
        "广角空镜, 无人物, 自然光照, 高质量, 细腻光影, 真实质感",
        mood_anchor,
    ]))
    log_token = model_log.set_context(project_id=project_id, episode_id=episode_id)
    try:
        console.print(f"[cyan]generating reference image for set {name}…[/]")
        image_url = npc_mod._call_t2i(
            prompt,
            negative_prompt="低分辨率, 错误, 残缺, 透视错误, 多余物品, 现代乱杂, 人物",
            size="1280*720",
        )
    finally:
        model_log.reset_context(log_token)

    out_path = set_dir / f"{name}.png"
    npc_mod._download_image(image_url, out_path)
    console.print(f"[green]✓ set reference → {out_path}[/]")
    if episode_id:
        console.print(
            f"[dim]Run `./bin/videogen set init --project {project_id} "
            f"--episode {episode_id}` to include this set in movie_set.json.[/]"
        )
    else:
        console.print(
            f"[dim]Run `./bin/videogen set init --project {project_id} "
            f"--episode <EPISODE>` to pick this set up.[/]"
        )


# ---------- key props (关键道具) ----------------------------------------------
prop_app = typer.Typer(
    help="Manage 关键道具 / key props (folder-per-prop, two-tier project↔episode)",
)
app.add_typer(prop_app, name="prop")


@prop_app.command("init")
def prop_init(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
    no_upload: bool = typer.Option(False, "--no-upload", help="skip OSS upload (dry run)"),
):
    """Scan project + episode prop folders, build composites, upload, write props.json.

    Two tiers (episode overrides project) — same model as cast / movie-set:

      • projects/<id>/props/<name>/             ← shared props
      • projects/<id>/<episode>/props/<name>/   ← episode-only props

    Each prop lives in its own folder. Multi-image folders represent the
    *same* state from different angles and get composed into a 2/4/9-pane
    grid. Different narrative states (完整 / 起皱 / 撕碎) **must** be
    separate folders — never multiple state images in one folder.

    Props are *optional* — episodes with zero props are a no-op.
    """
    payload = prop_mod.init_episode(project_id, episode_id, do_upload=not no_upload)
    props = payload["props"]
    if not props:
        console.print(
            f"[yellow](no props found in {payload['project_props_dir']} "
            f"or {payload['episode_props_dir']})[/]"
        )
        console.print(
            f"  scaffold one with: ./bin/videogen prop scaffold --project {project_id} "
            f"--name \"<prop name>\""
        )
        return
    table = Table(title=f"Key props for {project_id}/{payload['episode_id']}")
    table.add_column("Name")
    table.add_column("Id")
    table.add_column("State")
    table.add_column("Source")
    table.add_column("Image")
    table.add_column("Card")
    table.add_column("Uploaded")
    for p in props:
        n_img = len(p.get("images_local", []))
        img_cell = Path(p["image_local"]).name + (
            f" (×{n_img}→grid)" if p.get("composite_image") else ""
        )
        src = p.get("source", "project")
        state_lbl = (p.get("card") or {}).get("front", {}).get("state") or "—"
        table.add_row(
            p["name"],
            p.get("id", "?"),
            state_lbl,
            f"[bold magenta]{src}[/]" if src == "episode" else src,
            img_cell,
            "✓" if p.get("card") else "—",
            "✓" if p.get("image_url") else "—",
        )
    console.print(table)


@prop_app.command("ls")
def prop_ls(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
):
    """Print props.json for the episode."""
    typer.echo(json.dumps(
        prop_mod.load(project_id, episode_id), ensure_ascii=False, indent=2,
    ))


@prop_app.command("scaffold")
def prop_scaffold(
    name: str = typer.Option(..., "--name", help="prop display name, e.g. 红包-完整"),
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str | None = typer.Option(
        None, "--episode", "-e",
        help="if set, scaffold under projects/<id>/<episode>/props/<name>/ "
             "(episode-only prop). Default: project-shared prop.",
    ),
    overwrite: bool = typer.Option(False, "--force"),
):
    """Scaffold ``<props_dir>/<name>/prop.md`` with a fillable template.

    Defaults to the **project** tier (shared across all episodes). Pass
    ``--episode`` for a one-off prop. If the prop has multiple narrative
    states (e.g. 红包 → 完整 / 起皱 / 撕碎), scaffold each state as a
    separate folder with the ``<name>-<state>`` naming convention.
    """
    if episode_id:
        root = prop_mod.episode_props_dir(project_id, episode_id)
    else:
        root = prop_mod.project_props_dir(project_id)
    prop_dir = root / name
    prop_dir.mkdir(parents=True, exist_ok=True)
    out = prop_dir / prop_mod.PROP_FILENAME
    if out.exists() and not overwrite:
        console.print(f"[red]{out} exists; use --force to overwrite[/]")
        raise typer.Exit(1)
    out.write_text(prop_mod.PROP_TEMPLATE.format(name=name), encoding="utf-8")
    console.print(f"[green]✓ wrote {out}[/]")
    console.print(
        f"  drop a reference image into {prop_dir}/, then re-run "
        f"`./bin/videogen prop init --project {project_id} "
        f"--episode {episode_id or '<EPISODE>'}`."
    )


@prop_app.command("generate")
def prop_generate(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str | None = typer.Option(
        None, "--episode", "-e",
        help="save into the episode's props/ folder (episode-only). "
             "Omit to save into the project's shared props/.",
    ),
    name: str = typer.Option(..., "--name", help="prop display name"),
    description: str = typer.Option(
        ..., "--desc",
        help="Detailed description for image generation: 材质 / 颜色 / 形状 / 关键细节",
    ),
    mood_anchor: str = typer.Option(
        "", "--mood",
        help="project mood_anchor for style consistency (default: from lore.md)",
    ),
):
    """Generate a reference image for a prop via wan2.6-t2i.

    Useful when you have no on-set photo and want the model to invent a
    consistent prop based on a textual brief. The generated image is a
    clean, centred product-style shot ideal for r2v reference.
    """
    if not mood_anchor:
        lore = lore_mod.load(project_id, projects_dir=SETTINGS.projects_dir)
        if lore and lore.front.mood_anchor:
            mood_anchor = lore.front.mood_anchor

    if episode_id:
        prop_dir = prop_mod.episode_props_dir(project_id, episode_id) / name
    else:
        prop_dir = prop_mod.project_props_dir(project_id) / name
    prop_dir.mkdir(parents=True, exist_ok=True)

    prompt = ", ".join(filter(None, [
        f"道具实拍照, {name}",
        description,
        # Product-style framing makes the prop unambiguous as a reference.
        "居中构图, 简洁背景, 柔和光照, 无人物, 无干扰元素, 高清细节, 真实质感",
        mood_anchor,
    ]))
    log_token = model_log.set_context(project_id=project_id, episode_id=episode_id)
    try:
        console.print(f"[cyan]generating reference image for prop {name}…[/]")
        image_url = npc_mod._call_t2i(
            prompt,
            negative_prompt="低分辨率, 错误, 残缺, 透视错误, 多余物品, 人物, 文字, 水印",
            size="1024*1024",
        )
    finally:
        model_log.reset_context(log_token)

    out_path = prop_dir / f"{name}.png"
    npc_mod._download_image(image_url, out_path)
    console.print(f"[green]✓ prop reference → {out_path}[/]")
    if episode_id:
        console.print(
            f"[dim]Run `./bin/videogen prop init --project {project_id} "
            f"--episode {episode_id}` to include this prop in props.json.[/]"
        )
    else:
        console.print(
            f"[dim]Run `./bin/videogen prop init --project {project_id} "
            f"--episode <EPISODE>` to pick this prop up.[/]"
        )


# ---------- bgm ---------------------------------------------------------------
bgm_app = typer.Typer(
    help="Manage background music (folder-per-tier, two-tier project↔episode)",
)
app.add_typer(bgm_app, name="bgm")


@bgm_app.command("ls")
def bgm_ls(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
):
    """List BGM tracks visible to the episode (project + episode tier merged)."""
    tracks = bgm_mod.discover(project_id, episode_id)
    if not tracks:
        console.print(
            f"[yellow](no bgm files under projects/{project_id}/bgm/ "
            f"or projects/{project_id}/<episode>/bgm/)[/]"
        )
        return
    table = Table(title=f"BGM for {project_id}/{state.normalize_episode_id(episode_id)}")
    table.add_column("Name")
    table.add_column("File")
    table.add_column("Source")
    table.add_column("Size")
    for t in tracks:
        src = t["source"]
        table.add_row(
            t["name"],
            t["file"],
            f"[bold magenta]{src}[/]" if src == "episode" else src,
            f"{t['size_bytes']/1024/1024:.2f} MB",
        )
    console.print(table)


@bgm_app.command("discover")
def bgm_discover(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
    json_out: bool = typer.Option(True, "--json/--no-json", help="emit JSON for the producer agent"),
):
    """Producer entry point at GATE 0.5 — JSON-friendly BGM probe.

    Exit code 0 if at least one track is detected (producer should ask
    the user how to use BGM); exit code 2 if no BGM exists (skip GATE).
    """
    tracks = bgm_mod.discover(project_id, episode_id)
    payload = {
        "project_id": project_id,
        "episode_id": state.normalize_episode_id(episode_id),
        "project_bgm_dir": str(bgm_mod.project_bgm_dir(project_id)),
        "episode_bgm_dir": str(bgm_mod.episode_bgm_dir(project_id, episode_id)),
        "has_bgm": bool(tracks),
        "tracks": tracks,
    }
    if json_out:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if not tracks:
            console.print(
                f"[yellow]no BGM detected[/] under "
                f"{payload['project_bgm_dir']} or {payload['episode_bgm_dir']}"
            )
        else:
            console.print(f"[green]{len(tracks)} BGM track(s) detected:[/]")
            for t in tracks:
                console.print(f"  · {t['name']} ({t['file']}, {t['source']})")
    raise typer.Exit(code=0 if tracks else 2)


@bgm_app.command("configure")
def bgm_configure(
    project_id: str = typer.Option(..., "--project", "-p"),
    episode_id: str = typer.Option(..., "--episode", "-e"),
    mode: str = typer.Option(
        ..., "--mode",
        help="off | global | scene. off = detected but skip; global = "
             "one track for the whole video (use --track); scene = "
             "per-scene via Scene.bgm_track (director assigns).",
    ),
    forbid_model_bgm: bool = typer.Option(
        True, "--forbid-model-bgm/--allow-model-bgm",
        help="Inject a 'no music in the clip' directive into every shot "
             "prompt to prevent conflicts with the stitched BGM. "
             "Recommended on whenever you stitch your own BGM.",
    ),
    track: str | None = typer.Option(
        None, "--track",
        help="Track name (filename stem) for --mode=global. Must exist "
             "under projects/<id>/bgm/ or projects/<id>/<episode>/bgm/.",
    ),
    volume: float = typer.Option(0.25, "--volume", help="BGM gain 0.0..1.0 (default 0.25)"),
    fade_in_s: float = typer.Option(0.5, "--fade-in", help="seconds"),
    fade_out_s: float = typer.Option(1.0, "--fade-out", help="seconds"),
    disable: bool = typer.Option(
        False, "--disable",
        help="Set enabled=False without changing mode/track. Useful when "
             "you keep forbid_model_bgm=True for clean clips but ship "
             "the video without mixed music.",
    ),
):
    """Write storyboard.bgm into the existing storyboard.json.

    Idempotent: re-run to switch modes or tweak volume. Validates the
    track name against the bgm/ folder and against any per-scene tags.
    """
    if mode not in ("off", "global", "scene"):
        _bail(f"unknown --mode {mode!r}; valid: off | global | scene")

    raw = state.read_json(project_id, "storyboard.json", episode_id=episode_id)
    if not raw:
        _bail(
            f"storyboard.json missing for {project_id}/"
            f"{state.normalize_episode_id(episode_id)} — compile scenes first."
        )

    enabled = (not disable) and mode != "off"

    if mode == "global" and enabled:
        if not track:
            _bail("--track is required when --mode=global")
        if bgm_mod.resolve_track(project_id, episode_id, track) is None:
            available = ", ".join(
                t["name"] for t in bgm_mod.discover(project_id, episode_id)
            ) or "(none)"
            _bail(
                f"track {track!r} not found under bgm/. Available: {available}"
            )

    if mode == "scene" and enabled:
        sb_preview = Storyboard.model_validate(raw)
        tagged = [s for s in sb_preview.scenes if s.bgm_track]
        if not tagged:
            console.print(
                f"[yellow]⚠[/] mode=scene but no Scene.bgm_track is set yet. "
                f"The director should assign per-scene tracks in "
                f"scenes/scene-NN.json (then rerun `scene compile`)."
            )
        else:
            unresolved: list[tuple[str, str]] = []
            for sc in tagged:
                if bgm_mod.resolve_track(project_id, episode_id, sc.bgm_track) is None:
                    unresolved.append((sc.id, sc.bgm_track))
            if unresolved:
                available = ", ".join(
                    t["name"] for t in bgm_mod.discover(project_id, episode_id)
                ) or "(none)"
                console.print("[yellow]unresolved scene BGM tracks:[/]")
                for sid, tname in unresolved:
                    console.print(f"  {sid} → {tname!r}")
                console.print(f"  available: {available}")

    cfg = BGMConfig(
        enabled=enabled,
        mode=mode,  # type: ignore[arg-type]
        forbid_model_bgm=forbid_model_bgm,
        track=track if mode == "global" else None,
        volume=volume,
        fade_in_s=fade_in_s,
        fade_out_s=fade_out_s,
    )
    raw["bgm"] = cfg.model_dump()

    sb = Storyboard.model_validate(raw)
    state.write_json(project_id, "storyboard.json", sb.model_dump(), episode_id=episode_id)
    console.print(
        f"[green]✓ storyboard.bgm written: mode={cfg.mode} "
        f"enabled={cfg.enabled} forbid_model_bgm={cfg.forbid_model_bgm}"
        + (f" track={cfg.track}" if cfg.track else "")
        + f" volume={cfg.volume}[/]"
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

    # Cross-check scene.set_id against movie_set.json (soft warning).
    set_data = movie_set_mod.load(project_id, episode_id)
    known_sets = {s["name"] for s in set_data.get("sets", [])}
    unknown_sets: list[tuple[str, str]] = []
    for sc in sb.scenes:
        if sc.set_id and sc.set_id not in known_sets:
            unknown_sets.append((sc.id, sc.set_id))
    if unknown_sets:
        console.print(
            "[yellow]scenes referencing unknown movie sets "
            "(set reference image won't attach):[/]"
        )
        for sid, set_id in unknown_sets:
            console.print(f"  {sid} → set_id={set_id!r}")
        console.print(
            f"  fix: add a folder under projects/{project_id}/movie-set/{set_id}/ "
            f"or projects/{project_id}/<episode>/movie-set/{set_id}/, then "
            f"run `./bin/videogen set init --project {project_id} "
            f"--episode {episode_id}`."
        )

    # Cross-check shot.props against props.json (soft warning).
    prop_data = prop_mod.load(project_id, episode_id)
    known_props = {p["name"] for p in prop_data.get("props", [])}
    unknown_props: list[tuple[str, str]] = []
    for s in sb.shots:
        for pname in s.props:
            if pname not in known_props:
                unknown_props.append((s.id, pname))
    if unknown_props:
        console.print(
            "[yellow]shots referencing unknown key props "
            "(prop reference image won't attach):[/]"
        )
        for sid, pname in unknown_props:
            console.print(f"  {sid} → prop={pname!r}")
        console.print(
            f"  fix: add a folder under projects/{project_id}/props/<name>/ "
            f"(or projects/{project_id}/<episode>/props/<name>/), then "
            f"run `./bin/videogen prop init --project {project_id} "
            f"--episode {episode_id}`."
        )

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

    by_kind: dict[str, int] = {}
    for s in sb.shots:
        by_kind[s.kind] = by_kind.get(s.kind, 0) + s.duration

    payload = {
        "project_id": project_id,
        "episode_id": state.normalize_episode_id(episode_id),
        "shots": n_shots,
        "total_duration_s": total_s,
        "target_duration_s": sb.target_duration_s,
        "wall_clock_min_estimate": round(wall_min, 1),
        "resolution": sb.resolution,
        "ratio": sb.ratio,
        "duration_by_kind_s": by_kind,
        "provider": sb.provider or SETTINGS.video_provider,
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
        table.add_row("provider", payload["provider"])
        table.add_row("duration by kind",
                     ", ".join(f"{k}: {d}s" for k, d in by_kind.items()))
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
        scene_table.add_column("Description(60)")
        scene_table.add_column("Characters")
        scene_table.add_column("Set")
        scene_table.add_column("Seed")
        for sc in sb.scenes:
            scene_table.add_row(
                sc.id, sc.name,
                (sc.description[:60] + "…") if len(sc.description) > 60 else sc.description,
                ",".join(sc.characters_present) or "—",
                sc.set_id or "—",
                str(sc.seed) if sc.seed else "—",
            )
        console.print(scene_table)
        console.print("")

    provider_name = sb.provider or SETTINGS.video_provider
    try:
        provider = get_provider(provider_name)
        provider_label = (
            f"{provider.name} (t2v={provider.model_for('t2v')}, "
            f"i2v={provider.model_for('i2v')}, r2v={provider.model_for('r2v')})"
        )
    except ValueError:
        provider_label = f"{provider_name} (unknown!)"
    console.print(f"[dim]video provider: {provider_label}[/]")
    mode_label = sb.mode
    if sb.mode == "narration":
        nv = sb.narrator_voice or SETTINGS.narrator_voice
        n_narr = sum(1 for s in sb.shots if s.role == "narration")
        n_drama = len(sb.shots) - n_narr
        mode_label = (
            f"narration (旁白解说) · {n_narr} narration shots / {n_drama} drama shots · "
            f"voice={nv}"
        )
    console.print(f"[dim]episode mode: {mode_label}[/]")
    if sb.bgm is not None:
        bgm_label = (
            f"mode={sb.bgm.mode} enabled={sb.bgm.enabled} "
            f"forbid_model_bgm={sb.bgm.forbid_model_bgm}"
            + (f" track={sb.bgm.track}" if sb.bgm.track else "")
            + f" volume={sb.bgm.volume}"
        )
        console.print(f"[dim]bgm: {bgm_label}[/]")

    table = Table(title=sb.title)
    table.add_column("ID"); table.add_column("Scene"); table.add_column("Dur")
    table.add_column("Kind"); table.add_column("Role"); table.add_column("Cast")
    table.add_column("Set"); table.add_column("Props"); table.add_column("Purpose(40)")
    table.add_column("Prompt(50)"); table.add_column("Anchor")
    anchor = (lore.front.mood_anchor if lore else None) or ""
    scene_lookup = sb.scene_map()
    for s in sb.shots:
        anchor_hit = "✓" if (anchor and anchor in s.prompt) else ("—" if anchor else " ")
        np = s.narrative_purpose or ""
        np_cell = (np[:40] + "…") if len(np) > 40 else (np or "[red]—[/]")
        role_cell = (
            f"[magenta]{s.role}[/]" if s.role == "narration" else s.role
        )
        # Show the *effective* set_id (per-shot override > scene default).
        from .storyboard import _effective_set
        eff_set = _effective_set(s, scene_lookup.get(s.scene))
        if s.set_id is not None and s.set_id != (scene_lookup.get(s.scene).set_id if scene_lookup.get(s.scene) else None):
            set_cell = f"[yellow]{eff_set or '(none)'}*[/]"  # * = per-shot override
        else:
            set_cell = eff_set or "—"
        props_cell = ",".join(s.props) if s.props else "—"
        table.add_row(
            s.id, s.scene, f"{s.duration}s",
            s.kind, role_cell,
            ",".join(s.characters) or "—",
            set_cell,
            props_cell,
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
    mode: str = typer.Option(
        "drama", "--mode",
        help="drama (default) | narration. narration emits a 节拍式 template.",
    ),
):
    """Create empty scenes/scene-NN.md template for the screenwriter."""
    if mode not in ("drama", "narration"):
        _bail(f"unknown --mode {mode!r}; valid: drama | narration")
    out = scene_mod.scaffold_scene(project_id, episode_id, num, force=force, mode=mode)
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
    provider: str | None = typer.Option(
        None, "--provider",
        help="Pin the video model family in storyboard.provider "
             "(wan | happyhorse). Default: VIDEOGEN_VIDEO_PROVIDER env var.",
    ),
    mode: str = typer.Option(
        "drama", "--mode",
        help="Pin the episode mode in storyboard.mode "
             "(drama | narration). drama = 短剧, narration = 旁白解说.",
    ),
    narrator_voice: str | None = typer.Option(
        None, "--narrator-voice",
        help="Default TTS voice for narration mode. Falls back to VIDEOGEN_NARRATOR_VOICE.",
    ),
):
    """Merge scenes/scene-*.md → script.md and scenes/scene-*.json → storyboard.json."""
    if provider is not None and provider not in list_providers():
        _bail(f"unknown --provider {provider!r}; valid: {list_providers()}")
    if mode not in ("drama", "narration"):
        _bail(f"unknown --mode {mode!r}; valid: drama | narration")
    try:
        result = scene_mod.compile_episode(
            project_id, episode_id,
            title=title, synopsis=synopsis, target_duration_s=target,
            provider=provider, mode=mode, narrator_voice=narrator_voice,
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
    provider: str | None = typer.Option(
        None, "--provider",
        help="Override video model family for this run (wan | happyhorse). "
             "Default: storyboard.provider → VIDEOGEN_VIDEO_PROVIDER → happyhorse.",
    ),
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

    if provider is not None and provider not in list_providers():
        _bail(
            f"unknown --provider {provider!r}; valid: {list_providers()}"
        )

    try:
        out = render_mod.render_all(
            project_id, episode_id, sb,
            only_missing=not force,
            cfg=cfg,
            concurrency=concurrency,
            shot_ids=[shot_id] if shot_id else None,
            reset=reset_attempts,
            provider_override=provider,
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
    try:
        cast_data = cast_mod.load(project_id, episode_id)
    except FileNotFoundError:
        cast_data = None
    log_token = model_log.set_context(
        project_id=project_id, episode_id=episode_id,
        shot_id=shot_id, version=attempt.get("version"),
    )
    try:
        review = review_mod.review_clip(
            attempt["video_url"], shot=shot, scene=scene, lore=lore,
            cast_data=cast_data,
            threshold=threshold,
        )
    finally:
        model_log.reset_context(log_token)
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

    # If the storyboard configures per-scene BGM, mix each scene's chunk
    # individually BEFORE concat so each scene gets its own underscore.
    # For global BGM (or no BGM) we concat first and mix once at the end.
    bgm_cfg = sb.bgm
    mixing_per_scene = (
        bgm_cfg is not None
        and bgm_cfg.enabled
        and bgm_cfg.mode == "scene"
    )

    if mixing_per_scene:
        # Group the resolved winner clips by scene id, preserving order.
        scene_id_for_shot = {s.id: s.scene for s in sb.shots}
        scene_chunks: list[tuple[str, list[Path]]] = []
        for clip in clips:
            shot_id = clip.stem  # winner clip is named S01-001.mp4 or .../S01-001-verN.mp4
            base = shot_id.split("-ver")[0]
            scid = scene_id_for_shot.get(base, "")
            if not scene_chunks or scene_chunks[-1][0] != scid:
                scene_chunks.append((scid, []))
            scene_chunks[-1][1].append(clip)

        mixed_dir = edir / "final" / "_bgm_tmp"
        mixed_dir.mkdir(parents=True, exist_ok=True)
        mixed_chunks: list[Path] = []
        scene_lookup = sb.scene_map()
        for idx, (scid, scene_clips) in enumerate(scene_chunks):
            chunk_out = mixed_dir / f"scene-{idx:02d}.mp4"
            ff.concat(scene_clips, chunk_out, crossfade_s=0.0)
            scene = scene_lookup.get(scid)
            track_name = scene.bgm_track if scene else None
            if track_name:
                track_path = bgm_mod.resolve_track(project_id, episode_id, track_name)
                if track_path is None:
                    console.print(
                        f"[yellow]· scene {scid} bgm_track={track_name!r} "
                        f"could not be resolved — leaving scene without BGM[/]"
                    )
                else:
                    mixed = mixed_dir / f"scene-{idx:02d}-bgm.mp4"
                    ff.mix_bgm(
                        chunk_out, track_path, mixed,
                        volume=bgm_cfg.volume,
                        fade_in_s=bgm_cfg.fade_in_s,
                        fade_out_s=bgm_cfg.fade_out_s,
                    )
                    chunk_out.unlink(missing_ok=True)
                    chunk_out = mixed
            mixed_chunks.append(chunk_out)

        ff.concat(mixed_chunks, out, crossfade_s=crossfade)
        for p in mixed_dir.iterdir():
            p.unlink(missing_ok=True)
        mixed_dir.rmdir()
    else:
        ff.concat(clips, out, crossfade_s=crossfade)
        if bgm_cfg and bgm_cfg.enabled and bgm_cfg.mode == "global" and bgm_cfg.track:
            track_path = bgm_mod.resolve_track(project_id, episode_id, bgm_cfg.track)
            if track_path is None:
                console.print(
                    f"[yellow]· bgm.track={bgm_cfg.track!r} could not be "
                    f"resolved — final video shipped without BGM[/]"
                )
            else:
                premix = out.with_name(out.stem + ".premix.mp4")
                out.rename(premix)
                import math
                bgm_delta_lu = -14.0 + 20.0 * math.log10(max(bgm_cfg.volume, 0.01) / 0.25)
                ff.mix_bgm(
                    premix, track_path, out,
                    bgm_delta_lu=bgm_delta_lu,
                    fade_in_s=bgm_cfg.fade_in_s,
                    fade_out_s=bgm_cfg.fade_out_s,
                )
                premix.unlink(missing_ok=True)
                console.print(
                    f"[dim]· mixed global BGM {bgm_cfg.track!r} "
                    f"@ volume={bgm_cfg.volume} (bgm_delta={bgm_delta_lu:+.1f} LU)[/]"
                )

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


# ---------- tts ---------------------------------------------------------------
tts_app = typer.Typer(help="Narration TTS (qwen3-tts-flash) — used by narration-mode render")
app.add_typer(tts_app, name="tts")


@tts_app.command("synth")
def tts_synth(
    text: str = typer.Option(..., "--text", help="text to synthesize"),
    out: Path = typer.Option(..., "--out", help="output .wav path"),
    voice: str | None = typer.Option(None, "--voice", help="default: VIDEOGEN_NARRATOR_VOICE"),
    language: str | None = typer.Option(None, "--language", help="default: VIDEOGEN_NARRATOR_LANGUAGE"),
    model: str | None = typer.Option(None, "--model", help="default: VIDEOGEN_NARRATOR_TTS_MODEL"),
    speech_rate: float | None = typer.Option(
        None,
        "--speech-rate",
        help="ffmpeg atempo after synthesis; default VIDEOGEN_NARRATOR_SPEECH_RATE (1.2)",
    ),
):
    """Manually synthesize a narration line. Useful for previewing voices."""
    try:
        path = tts_mod.synth(
            text,
            out_path=out,
            voice=voice,
            language=language,
            model=model,
            speech_rate=speech_rate,
        )
    except Exception as e:  # noqa: BLE001
        _bail(str(e))
    console.print(f"[green]✓ wrote {path}[/]")


# ---------- task --------------------------------------------------------------
task_app = typer.Typer(help="Inspect/manage DashScope video tasks directly")
app.add_typer(task_app, name="task")


@task_app.command("query")
def task_query(
    task_id: str,
    provider: str | None = typer.Option(None, "--provider"),
):
    """Query a DashScope async task (the endpoint is the same for all providers)."""
    p = get_provider(provider)
    typer.echo(json.dumps(p.query(task_id), ensure_ascii=False, indent=2))


@task_app.command("wait")
def task_wait(
    task_id: str,
    interval: int = 15,
    provider: str | None = typer.Option(None, "--provider"),
):
    p = get_provider(provider)
    typer.echo(json.dumps(p.wait(task_id, interval=interval), ensure_ascii=False, indent=2))


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
