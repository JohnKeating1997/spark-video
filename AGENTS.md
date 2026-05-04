# AGENTS.md — entry point for any agentic CLI working in this repo

This repo is a **director's toolbox** for generating long-form (3–10 min) AI
videos with consistent characters using **Wan 2.7** models on Alibaba DashScope.

## Roles

- **You (the agent)** = director. You write the script + storyboard, then drive
  the `videogen` CLI to render and stitch the final video.
- **`videogen` CLI** = your crew. It handles all DashScope API calls, OSS
  uploads, ffmpeg work, and resumable state.

## Always-on rules

1. Read `.claude/skills/video-director/SKILL.md` before doing any video work.
2. Never call the Wan HTTP API yourself — go through `videogen` subcommands.
3. Never invent character names not in `projects/<id>/cast.json`.
4. Always run `videogen storyboard validate` before `videogen render`.
5. State of every project lives in `projects/<id>/`. Treat it as the source of
   truth — read it before answering "what's the status?" questions.

## Slash commands

- `/cast-init <id>` — initialize cast from `./cast/`.
- `/storyboard <id> "<premise>"` — write script + storyboard.
- `/render <id>` — render + stitch.
- `/retry <id> <shot>` — fix a failed shot.

## CLI quick reference

```bash
videogen doctor                                  # env check
videogen cast init  --project <id>
videogen cast ls    --project <id>
videogen storyboard validate --project <id>
videogen storyboard show     --project <id>
videogen render --project <id> [--shot <id>] [--force]
videogen stitch --project <id> [--crossfade 0.5]
videogen task query <task_id>
videogen task wait  <task_id>
```

## Schema

Storyboard shape: see `src/videogen/storyboard.py` (`Shot` + `Storyboard`
Pydantic models). The CLI validates against this — no surprises.
