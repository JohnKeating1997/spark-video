# AGENTS.md — entry point for any agentic CLI working in this repo

This repo is a **director's toolbox** for generating long-form (3–10 min) AI
videos with consistent characters using **Wan 2.7** models on Alibaba DashScope.

## Architecture — Multi-Agent Production Team

The pipeline uses **4 specialized roles** coordinated by a producer:

```
User premise
    │
    ▼
┌─────────────────────────────────────────────────┐
│  PRODUCER (episode orchestrator)                │
│                                                 │
│  ┌───────────┐    ┌──────────┐    ┌──────────┐ │
│  │ Screenwriter│──▶│ Director │──▶│VFX Review│ │
│  │ (编剧)     │    │ (导演)   │◀──│(视效审核) │ │
│  └───────────┘    └──────────┘    └──────────┘ │
│                        │                        │
│                        ▼                        │
│               ┌────────────────┐                │
│               │ CLI (videogen) │                │
│               │ render + stitch│                │
│               └────────────────┘                │
└─────────────────────────────────────────────────┘
    │
    ▼
Final mp4
```

| Role | Skill file | Responsibility | Output |
|------|-----------|----------------|--------|
| **Producer** | (episode.md) | Orchestrate team, manage 4 user gates | Coordination |
| **Screenwriter** | `screenwriter/SKILL.md` | Polish premise into structured screenplay | `script.md` |
| **Director** | `video-director/SKILL.md` | Script → scenes + shots, prompt engineering | `storyboard.json` |
| **VFX Reviewer** | `vfx-reviewer/SKILL.md` | Pre-render quality gate (12-point checklist) | Review report |
| **CLI** | — | API calls, OSS uploads, ffmpeg, state | Rendered clips + final mp4 |

### Role boundaries (hard rules)

- **Screenwriter** writes narrative. Does NOT know about Wan models,
  `图1` syntax, or prompt engineering.
- **Director** writes technical storyboard. Does NOT write the screenplay.
- **VFX Reviewer** finds problems. Does NOT modify the storyboard.
- **CLI** executes. Does NOT make creative decisions.

## Always-on rules

1. Read the relevant skill file before doing any work in that role.
2. Never call the Wan HTTP API yourself — go through `videogen` subcommands.
3. Never invent character names not in `projects/<id>/cast.json`.
4. Read `projects/<id>/lore.md` BEFORE writing the script. If absent,
   scaffold with `./bin/videogen lore template --project <id>` and fill at
   least `mood_anchor`, `genre`, `visual_style`, `forbidden`.
5. Append `lore.mood_anchor` to **every** shot prompt verbatim — this is
   the single biggest visual-cohesion lever for long videos.
6. Always run `videogen storyboard validate` before `videogen render`.
7. **Always run `videogen storyboard estimate` before `videogen render`** and
   surface the numbers to the user. If the CLI exits 2 (total duration over
   `VIDEOGEN_LONG_CONFIRM_S`), require explicit user approval before passing
   `--yes` to `render`.
8. Default each shot's duration to the model maximum (15s for t2v/i2v/r2v).
   Only shorten when the script genuinely needs a quick beat.
9. State of every project lives in `projects/<id>/`. Treat it as the source of
   truth — read it before answering "what's the status?" questions.

## Privacy / git hygiene

- `cast/` (user portraits + voice samples) and `projects/` (rendered clips) are
  **gitignored**. Never `git add -f` them.
- A pre-commit hook in `scripts/pre-commit` blocks accidental commits of cast
  assets, render outputs, or any file >5 MB. Install once with
  `bash scripts/install-hooks.sh`.

## How to invoke the CLI from an agent shell

Always call **`./bin/videogen`** (the shim — works regardless of whether the
Python venv is activated). Never call bare `videogen` from agent-spawned shells
unless you have first verified it's on PATH.

## Slash commands

### Full pipeline
- `/episode <id> "<premise>"` — autopilot: screenwriter → director → VFX review → render → stitch.

### Individual roles (can be run standalone)
- `/screenwriter <id> "<premise>"` — write `script.md` only.
- `/director <id>` — compile `script.md` into `storyboard.json`.
- `/vfx-review <id>` — quality-gate a storyboard before render.

### Utilities
- `/cast-init <id>` — initialize cast from `./cast/`.
- `/render <id>` — render + stitch (requires approved storyboard).
- `/retry <id> <shot>` — fix a failed shot.
- `/storyboard <id>` — alias for `/director`.

## CLI quick reference

```bash
./bin/videogen doctor                                  # env check
./bin/videogen cast init  --project <id>
./bin/videogen cast ls    --project <id>
./bin/videogen cast soul show     --project <id>      # dump parsed soul cards
./bin/videogen cast soul template --name <NAME> [--project <id>]
./bin/videogen cast generate-npc --project <id> --name <NAME> --desc "<appearance>" [--mood "<anchor>"]
./bin/videogen lore template  --project <id> --title "<title>"
./bin/videogen lore show      --project <id>          # the world bible
./bin/videogen lore validate  --project <id>
./bin/videogen storyboard validate --project <id>
./bin/videogen storyboard show     --project <id>     # shows scenes + shots + mood_anchor
./bin/videogen storyboard estimate --project <id>     # exits 2 if total > VIDEOGEN_LONG_CONFIRM_S
./bin/videogen render --project <id> [--shot <id>] [--force] [--yes]
./bin/videogen stitch --project <id> [--crossfade 0.5]
./bin/videogen task query <task_id>
./bin/videogen task wait  <task_id>
```

## Schema

Storyboard shape: see `src/videogen/storyboard.py` (`Scene` + `Shot` +
`Storyboard` Pydantic models). The `scenes` array defines per-scene
environments; `shots` reference scenes by `scene` id. The CLI validates
against this — no surprises.
