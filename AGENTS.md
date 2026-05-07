# AGENTS.md — entry point for any agentic CLI working in this repo

This repo is a **director's toolbox** for generating long-form (3–10 min) AI
videos with consistent characters using **Wan 2.7** models on Alibaba DashScope.

## Architecture — Multi-Agent Production Team

The pipeline uses **4 specialized roles** coordinated by a producer:

```
User premise (for one EPISODE of a project)
 │
 ▼
┌─────────────────────────────────────────────────┐
│ PRODUCER (episode orchestrator)                 │
│                                                 │
│  ┌───────────┐   ┌──────────┐   ┌──────────┐    │
│  │Screenwriter│──▶│ Director │──▶│VFX Review│    │
│  │   (编剧)   │   │  (导演)  │◀──│(视效审核)│    │
│  └───────────┘   └──────────┘   └──────────┘    │
│                       │                          │
│                       ▼                          │
│              ┌────────────────┐                  │
│              │ CLI (videogen) │                  │
│              │ render + stitch│                  │
│              └────────────────┘                  │
└─────────────────────────────────────────────────┘
 │
 ▼
Final mp4 (one per episode)
```

| Role             | Skill file                   | Responsibility                                 | Output                  |
|------------------|------------------------------|------------------------------------------------|-------------------------|
| **Producer**     | (episode.md)                 | Orchestrate team, manage 4 user gates          | Coordination            |
| **Screenwriter** | `screenwriter/SKILL.md`      | Polish premise into structured screenplay      | `script.md` (per ep)    |
| **Director**     | `video-director/SKILL.md`    | Script → scenes + shots, prompt engineering    | `storyboard.json`       |
| **VFX Reviewer** | `vfx-reviewer/SKILL.md`      | Pre-render quality gate (12-point checklist)   | Review report           |
| **CLI**          | —                            | API calls, OSS uploads, ffmpeg, state          | Rendered clips + mp4    |

### Role boundaries (hard rules)

- **Screenwriter** writes narrative. Does NOT know about Wan models,
  `图1` syntax, or prompt engineering.
- **Director** writes technical storyboard. Does NOT write the screenplay.
- **VFX Reviewer** finds problems. Does NOT modify the storyboard.
- **CLI** executes. Does NOT make creative decisions.

## Filesystem model — projects + episodes

A **project** is one show; an **episode** is a single ~3-min film inside it.

```
projects/<project_id>/
├── lore.md                            ← project-level world bible (shared)
├── cast/                              ← project mains (shared across eps)
│   └── <character_name>/
│       ├── cast.md                    ← soul card (front-matter + body)
│       ├── <portrait>.{png,jpg,webp}  ← any portrait filenames
│       └── <voice>.{mp3,wav}          ← any voice filenames
└── <episode_id>/                      ← e.g. episode-001, episode-002
    ├── script.md                      ← screenplay for this episode
    ├── storyboard.json                ← scenes + shots
    ├── cast.json                      ← built per episode
    ├── cast/                          ← episode-only NPCs (same folder layout)
    │   └── <npc_name>/
    │       ├── cast.md
    │       └── <npc_name>.png
    ├── cast_built/                    ← ASCII-renamed singletons + grids
    ├── clips/  frames/  final/  logs/
    └── state.json  shots_state.json
```

Folder name = character display name. Anything inside a character folder
belongs to that character — composites (multi-pane grids, multi-take voice
mixes) are built **only within one folder**, never blending different
characters.

## Always-on rules

1. Read the relevant skill file before doing any work in that role.
2. Never call the Wan HTTP API yourself — go through `videogen` subcommands.
3. Never invent character names not in `projects/<id>/<episode>/cast.json`.
4. Read `projects/<id>/lore.md` BEFORE writing the script. If absent,
   scaffold with `./bin/videogen lore template --project <id>` and fill at
   least `mood_anchor`, `genre`, `visual_style`, `forbidden`. Lore is
   **project-scoped** — one lore file shared across all episodes.
5. Append `lore.mood_anchor` to **every** shot prompt verbatim — this is
   the single biggest visual-cohesion lever for long videos.
6. Always run `videogen storyboard validate --project <id> --episode <ep>`
   before `videogen render`.
7. **Always run `videogen storyboard estimate --project <id> --episode <ep>`
   before `videogen render`** and surface the numbers to the user. If the
   CLI exits 2 (total duration over `VIDEOGEN_LONG_CONFIRM_S`), require
   explicit user approval before passing `--yes` to `render`.
8. Default each shot's duration to the model maximum (15s for t2v/i2v/r2v).
   Only shorten when the script genuinely needs a quick beat.
9. State of every episode lives in `projects/<id>/<episode>/`. Treat it as
   the source of truth — read it before answering "what's the status?"
   questions.
10. Episode IDs are normalized: pass `--episode 001` and the CLI maps it to
    the folder `episode-001`. Bare folder names (`--episode episode-001`)
    are also accepted.

## Privacy / git hygiene

- `cast/` (legacy global pool) and `projects/` (rendered clips, portraits,
  voice samples) are **gitignored**. Never `git add -f` them.
- A pre-commit hook in `scripts/pre-commit` blocks accidental commits of
  cast assets, render outputs, or any file >5 MB. Install once with
  `bash scripts/install-hooks.sh`.

## How to invoke the CLI from an agent shell

Always call **`./bin/videogen`** (the shim — works regardless of whether the
Python venv is activated). Never call bare `videogen` from agent-spawned shells
unless you have first verified it's on PATH.

## Slash commands

### Full pipeline
- `/episode <project> <episode> "<premise>"` — autopilot: screenwriter →
  director → VFX review → render → stitch.

### Individual roles (can be run standalone)
- `/screenwriter <project> <episode> "<premise>"` — write `script.md` only.
- `/director <project> <episode>` — compile `script.md` into `storyboard.json`.
- `/vfx-review <project> <episode>` — quality-gate a storyboard before render.

### Utilities
- `/cast-init <project> <episode>` — initialize cast.json for the episode.
- `/render <project> <episode>` — render + stitch (requires approved storyboard).
- `/retry <project> <episode> <shot>` — fix a failed shot.
- `/storyboard <project> <episode>` — alias for `/director`.

## CLI quick reference

```bash
./bin/videogen doctor                                              # env check

# Project-level (lore is shared across episodes)
./bin/videogen lore template --project <p> --title "<title>"
./bin/videogen lore show     --project <p>
./bin/videogen lore validate --project <p>

# Episode scaffolding
./bin/videogen episode init --project <p> --episode <e>            # mkdir scaffold
./bin/videogen episode ls   --project <p>                          # list episodes

# Cast (per episode — merges project mains + episode NPCs)
./bin/videogen cast init       --project <p> --episode <e>
./bin/videogen cast ls         --project <p> --episode <e>
./bin/videogen cast soul show  --project <p> --episode <e>
./bin/videogen cast soul template --project <p> [--episode <e>] --name <NAME>
./bin/videogen cast generate-npc  --project <p> [--episode <e>] \
        --name <NAME> --desc "<appearance>" [--mood "<anchor>"]

# Storyboard (per episode)
./bin/videogen storyboard validate --project <p> --episode <e>
./bin/videogen storyboard show     --project <p> --episode <e>
./bin/videogen storyboard estimate --project <p> --episode <e>     # exits 2 if over budget

# Render + stitch (per episode)
./bin/videogen render --project <p> --episode <e> [--shot <id>] [--force] [--yes]
./bin/videogen stitch --project <p> --episode <e> [--crossfade 0.5]

# Tasks
./bin/videogen task query <task_id>
./bin/videogen task wait  <task_id>
```

`cast soul template` and `cast generate-npc` default to the **project**
cast tier (shared mains). Add `--episode <e>` to put the new character into
that episode only.

## Schema

Storyboard shape: see `src/videogen/storyboard.py` (`Scene` + `Shot` +
`Storyboard` Pydantic models). The `scenes` array defines per-scene
environments; `shots` reference scenes by `scene` id. The CLI validates
against this — no surprises.
