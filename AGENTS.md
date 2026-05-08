# AGENTS.md — entry point for any agentic CLI working in this repo

This repo is a **director's toolbox** for generating long-form (3–10 min) AI
videos with consistent characters using **Wan 2.7** models on Alibaba DashScope.

## Architecture — Multi-Agent Production Team (parallel pipeline)

The pipeline is a **multi-agent collaboration** with three places where work
runs in parallel:

```
                                 ╔══════════════════════════════════════════╗
                                 ║ PRODUCER (.claude/commands/episode.md)   ║
                                 ╚══════════════════════════════════════════╝
                                                  │
                  Zone 1 ── per-scene parallel ───┴──────┐
                  ┌────────────────────────┐    ┌────────────────────┐
                  │ Screenwriter Agent     │═══▶│ Director Agent      │
                  │ (wraps 山音 编剧大师)   │    │ (wraps 山音 导演大师)│
                  │ scenes/scene-NN.md     │    │ scenes/scene-NN.json│
                  └────────────────────────┘    └────────────────────┘
                                                  │
                                                  ▼   scene compile
                                              storyboard.json
                                                  │
                                                  ▼
                          (optional) VFX Reviewer  ─── default: BYPASSED.
                                                  │   only when --vfx flag.
                                                  ▼
                  Zone 2 ── chain-DAG render ─────┘
                  CLI slices shots into chain groups (gating on
                  use_prev_last_frame_as_first). Groups run in parallel
                  via ThreadPoolExecutor; within a group still sequential.
                                                  │
                                                  ▼
                  Zone 3 ── per-clip review + retry ─┐
                  After each clip:
                    qwen3-vl-plus → score → ACCEPT / REJECT
                  REJECT (rounds 1..N-1) → CLI auto-rewrites prompt
                                            via qwen-text + re-renders
                                            (clip becomes ver2, ver3, …)
                  REJECT (round N) → write needs_director_rewrite.json,
                                      exit 3 → producer escalates to
                                      director subagent.
                  Pick best-of-N as winner if all attempts below threshold.
                                                  │
                                                  ▼
                                          stitch (winner_path per shot)
                                                  │
                                                  ▼
                                       final/<project>-<episode>.mp4
```

| Role | Skill file | Responsibility | Output |
|------|------------|----------------|--------|
| **Producer** | `.claude/commands/episode.md` | Orchestrate team, manage 4 user gates, fan out parallel subagents | Coordination |
| **Screenwriter** | `.claude/skills/screenwriter/SKILL.md` *(wraps `references/shanyin-screenwriting/SKILL.md`)* | Premise → `scenes/scene-NN.md` (one scene per file, sentinel `scene-NN.ready`) | per-scene markdown |
| **Director** | `.claude/skills/video-director/SKILL.md` *(wraps `references/shanyin-director/SKILL.md`)* | scene-NN.md → `scenes/scene-NN.json` (storyboard fragment, validated against `storyboard.py` schema) | per-scene JSON |
| **VFX Reviewer** *(opt-in)* | `.claude/skills/vfx-reviewer/SKILL.md` | Pre-render storyboard quality gate. Skipped unless `/episode … --vfx`. | report |
| **Video Reviewer** *(new)* | `.claude/skills/video-reviewer/SKILL.md` | Per-clip 0-10 scoring (logic / proportion / physics / style) via qwen3-vl-plus; drives auto-rewrite + escalation. | `reviews/<shot>-verN.json` |
| **CLI** | — | API calls, OSS uploads, ffmpeg, parallel render, review, stitch, state. | clips + final mp4 |

### Role boundaries (hard rules)

- **Screenwriter** writes narrative one scene at a time; does NOT know about
  Wan models, `图1` syntax, or prompt engineering.
- **Director** writes one storyboard fragment per scene; does NOT write
  the screenplay; respects `use_prev_last_frame_as_first=false` on every
  scene's first shot to keep the chain DAG wide (more parallelism).
- **VFX Reviewer** finds problems at the storyboard level; does NOT modify
  the storyboard.
- **Video Reviewer** scores rendered clips; does NOT modify storyboard.json
  itself — it produces an escalation report and hands off to the director.
- **CLI** executes. Does NOT make creative decisions.

## Filesystem model — projects + episodes

A **project** is one show; an **episode** is a single ~3-min film inside it.

```
projects/<project_id>/
├── lore.md                            ← project-level world bible (shared)
├── cast/                              ← project mains (shared across eps)
│   └── <character_name>/{cast.md,*.png,*.mp3}
└── <episode_id>/                      ← e.g. episode-001
    ├── direction.json                 ← per-episode 导演定调 (optional)
    ├── scenes/                        ← per-scene parallel pipeline (Zone 1)
    │   ├── scene-01.md                ← screenwriter output
    │   ├── scene-01.ready             ← sentinel: editor done with scene 01
    │   ├── scene-01.json              ← director output
    │   ├── scene-02.{md,ready,json}
    │   └── ...
    ├── script.md                      ← merged from scenes/*.md (auto)
    ├── storyboard.json                ← merged from scenes/*.json (auto, validated)
    ├── cast.json                      ← built per episode (project + episode merged)
    ├── cast/                          ← episode-only NPCs
    │   └── <npc_name>/{cast.md,*.png}
    ├── cast_built/                    ← ASCII-renamed singletons + grids
    ├── clips/
    │   ├── S01-001-ver1.mp4           ← versioned attempts
    │   ├── S01-001-ver2.mp4
    │   └── S01-001.mp4                ← copy of the winning version
    ├── frames/  S01-001-ver1_last.png ← per-attempt last frames
    ├── reviews/
    │   ├── S01-001-ver1.json          ← {score, breakdown, critique, verdict}
    │   └── escalation-S01-001.md      ← only when needs_director_rewrite=true
    ├── final/  logs/
    ├── shots_state.json               ← attempts[] + winner_version per shot
    ├── needs_director_rewrite.json    ← present only when render exits 3
    └── state.json
```

## Always-on rules

1. Read the relevant skill file before doing any work in that role.
   Screenwriter / director SKILL.md files are *wrappers* — also read the
   inner Shanyin SKILL each cites.
2. Never call the Wan / qwen HTTP API yourself — go through `videogen`
   subcommands (`render`, `review`, `task ...`).
3. Never invent character names not in `projects/<id>/<episode>/cast.json`.
4. Read `projects/<id>/lore.md` BEFORE writing any scene. If absent,
   scaffold with `./bin/videogen lore template --project <id>` and fill
   at least `mood_anchor`, `genre`, `visual_style`, `forbidden`. Lore is
   **project-scoped** — one file shared across all episodes.
5. Append `lore.mood_anchor` to **every** shot prompt verbatim — single
   biggest visual-cohesion lever for long videos.
6. **Editor and director run in parallel by scene.** Use the per-scene
   file model (`scenes/scene-NN.md` ↔ `scenes/scene-NN.json`) and the
   `scene ready` sentinel to coordinate.
7. **First shot of every scene** must have `use_prev_last_frame_as_first:
   false` unless you genuinely want a cross-scene chain. This unlocks
   parallel rendering.
8. Always run `videogen storyboard validate` AND `videogen render-graph`
   before `videogen render`. Surface the parallel group count to the user.
9. Always run `videogen storyboard estimate` before `videogen render`.
   If exit 2 (over `VIDEOGEN_LONG_CONFIRM_S`), require user approval
   before passing `--yes`.
10. Default each shot's duration to the model maximum (15s). Only shorten
    when the script genuinely needs a quick beat.
11. State of every episode lives in `projects/<id>/<episode>/`. Treat it
    as the source of truth.
12. Episode IDs are normalized: pass `--episode 001` → CLI maps to
    folder `episode-001`. Bare `--episode episode-001` also accepted.
13. **Per-clip review is on by default**. To run a render without
    qwen-vl scoring, pass `--no-review` to `render`.

## Privacy / git hygiene

- `cast/` (legacy global pool), `projects/` (rendered clips, portraits,
  voice samples), and the upstream Shanyin skill folders
  (`.claude/skills/*/references/shanyin-*`) are **gitignored**. Never
  `git add -f` them.
- Pre-commit hook in `scripts/pre-commit` blocks accidental commits of
  cast assets, render outputs, or any file >5 MB.
  Install once: `bash scripts/install-hooks.sh`.
- One-time skill install: `bash scripts/install-shanyin-skills.sh`
  populates the wrapper `references/` folders. Re-run to refresh.

## How to invoke the CLI from an agent shell

Always call **`./bin/videogen`** (the shim — works regardless of whether
the Python venv is activated). Never call bare `videogen` from
agent-spawned shells unless you have first verified it's on PATH.

## Slash commands

### Full pipeline
- `/episode <project> <episode> "<premise>" [--vfx]` — autopilot:
  per-scene editor↔director parallel → render (parallel + per-clip
  review + auto-rewrite + escalation) → stitch. `--vfx` opts into
  pre-render VFX review (default: bypassed).

### Per-scene (parallel pipeline)
- `/scene-write <project> <episode> <num> "<premise/note>"` — drive the
  screenwriter to produce a single `scenes/scene-NN.md`.
- `/scene-direct <project> <episode> <num>` — drive the director to
  emit `scenes/scene-NN.json` for an already-ready scene.

### Per-role (legacy / standalone)
- `/screenwriter <project> <episode> "<premise>"` — full screenplay (legacy single-file mode).
- `/director <project> <episode>` — full storyboard from existing script.md (legacy).
- `/vfx-review <project> <episode>` — opt-in pre-render quality gate.
- `/review <project> <episode> [<shot>]` — re-run video review on existing clips.

### Utilities
- `/cast-init <project> <episode>` — initialize cast.json for the episode.
- `/render <project> <episode>` — render + per-clip review + stitch.
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

# Per-scene parallel pipeline (Zone 1)
./bin/videogen scene scaffold --project <p> --episode <e> --num <N>      # template
./bin/videogen scene ready    --project <p> --episode <e> --num <N>      # editor signal
./bin/videogen scene status   --project <p> --episode <e>                # progress
./bin/videogen scene compile  --project <p> --episode <e>                # merge → script.md + storyboard.json

# Storyboard (per episode)
./bin/videogen storyboard validate --project <p> --episode <e>
./bin/videogen storyboard show     --project <p> --episode <e>
./bin/videogen storyboard estimate --project <p> --episode <e>     # exits 2 if over budget
./bin/videogen render-graph        --project <p> --episode <e>     # parallel chain group plan

# Render (Zone 2 + Zone 3) + review + stitch
./bin/videogen render --project <p> --episode <e> \
        [--shot <id>] [--force] [--reset-attempts] [--yes] \
        [--review/--no-review] [--score-threshold 7.0] \
        [--max-retry 3] [--auto-rewrite/--no-auto-rewrite] \
        [--concurrency 4]
./bin/videogen review --project <p> --episode <e> --shot <id> [--ver N]
./bin/videogen stitch --project <p> --episode <e> [--crossfade 0.5] \
        [--allow-below-threshold]

# Tasks
./bin/videogen task query <task_id>
./bin/videogen task wait  <task_id>
```

`render` exit codes: `0` ok · `1` invalid args / missing storyboard ·
`2` over budget · `3` one or more shots flagged for director rewrite
(escalation needed; producer reads `needs_director_rewrite.json`).

`cast soul template` and `cast generate-npc` default to the **project**
cast tier (shared mains). Add `--episode <e>` to put the new character
into that episode only.

## Schema

Storyboard shape: see `src/videogen/storyboard.py` (`Scene` + `Shot` +
`Storyboard` Pydantic models). Per-shot review state: see
`src/videogen/render.py` (`_empty_shot_record` for the `attempts[]` +
`winner_version` schema).

## Configuration knobs (.env)

Per-clip review + auto-rewrite (Zone 3):

| Var | Default | Meaning |
|-----|---------|---------|
| `VIDEOGEN_REVIEW_THRESHOLD` | `7.0` | ACCEPT if `score >= threshold` |
| `VIDEOGEN_REVIEW_MODEL` | `qwen3-vl-plus` | empty string → review disabled |
| `VIDEOGEN_REWRITE_MODEL` | `qwen-plus` | empty string → auto-rewrite disabled |
| `VIDEOGEN_MAX_RETRY` | `3` | rounds per shot before escalation |

Parallelism (Zone 2):

| Var | Default | Meaning |
|-----|---------|---------|
| `VIDEOGEN_MAX_CONCURRENCY` | `4` | parallel chain groups in `render` |
