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

## How to invoke the CLI from an agent shell

Always call **`./bin/videogen`** (the shim — works regardless of whether the
Python venv is activated). Never call bare `videogen` from agent-spawned shells
unless you have first verified it's on PATH.

## Slash commands

- `/cast-init <id>` — initialize cast from `./cast/`.
- `/storyboard <id> "<premise>"` — write script + storyboard.
- `/render <id>` — render + stitch.
- `/retry <id> <shot>` — fix a failed shot.

## CLI quick reference

```bash
./bin/videogen doctor                                  # env check
./bin/videogen cast init  --project <id>
./bin/videogen cast ls    --project <id>
./bin/videogen storyboard validate --project <id>
./bin/videogen storyboard show     --project <id>
./bin/videogen render --project <id> [--shot <id>] [--force]
./bin/videogen stitch --project <id> [--crossfade 0.5]
./bin/videogen task query <task_id>
./bin/videogen task wait  <task_id>
```

## Schema

Storyboard shape: see `src/videogen/storyboard.py` (`Shot` + `Storyboard`
Pydantic models). The CLI validates against this — no surprises.
