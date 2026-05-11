# videoGen — Long-form AI Video Director

Generate **3–10 minute** AI videos with consistent characters and scene
continuity, driven by **Claude Code** or **Qwen Code** as the directing
brain on top of Alibaba DashScope's video models. Two model families are
supported through a provider abstraction:

- **HappyHorse 1.0** *(default)* — `happyhorse-1.0-{t2v,i2v,r2v}`
- **Wan 2.7** — `wan2.7-{t2v-2026-04-25,i2v-2026-04-25,r2v}`

Pick the family per workspace (`VIDEOGEN_VIDEO_PROVIDER` in `.env`),
per episode (`scene compile --provider`), or per render
(`videogen render --provider`).

Two **production modes** are available — chosen at the very start of
`/episode`:

- **drama** (短剧, default) — 2–5 min original short. Long, dialog-driven
  shots. Today's flow.
- **narration** (旁白解说, "10 分钟带你看完 XX") — short visual beats
  whose original audio is stripped and replaced by `qwen3-tts-flash`
  voiceover via `ffmpeg.mux_audio`. Sidesteps the video models'
  long-form weakness (faces drift, no continuity, no music) by leaning
  on TTS to carry the story. Drama beats can still be mixed in.

> "像抽卡一样写视频" — type a premise, get a screenplay → storyboard → 35-shot
> finished mp4. Re-roll any shot, retry any scene, swap any actor.

## How the pieces fit

```
┌─────────────────────────────────────────────────────────────┐
│  Claude Code / Qwen Code  (LLM orchestration)                │
│  Producer (.claude/commands/episode.md)                      │
│   ├── Screenwriter (wraps 山音 编剧大师)  →  scenes/scene-NN.md│
│   ├── Director     (wraps 山音 导演大师)  →  scenes/scene-NN.json│
│   ├── VFX Reviewer (opt-in, --vfx)        →  pre-render gate  │
│   └── Video Reviewer                       →  per-clip 0-10 score│
└──────────────┬──────────────────────────────────────────────┘
               │ shell calls, JSON in / JSON out
               ▼
┌─────────────────────────────────────────────────────────────┐
│  videogen CLI  (Python · parallel engine)                    │
│  scene    →  per-scene scaffold / ready / compile (--provider)│
│  cast     →  scan ./cast, OSS upload, cast.json              │
│  providers →  Wan / HappyHorse adapters (submit + poll)       │
│             kind (t2v/i2v/r2v) → vendor model + req body     │
│  render   →  chain-DAG slicing, ThreadPoolExecutor parallel, │
│             versioned attempts, qwen3-vl-plus review,        │
│             qwen-text auto-rewrite, escalation               │
│  ffmpeg   →  last-frame extraction, concat, audio mux        │
│  tts      →  qwen3-tts-flash narration (used in narration mode)│
│  state    →  per-episode JSON, attempts[] + winner_version   │
└──────────────┬──────────────────────────────────────────────┘
               ▼
       DashScope (Wan / HappyHorse) + qwen-vl + qwen-text + ffmpeg + OSS
```

### Three places it runs in parallel

1. **Editor ↔ Director, by scene** — producer fans out so the director
   storyboards scene N while the editor is still drafting scene N+1.
   Coordinated via per-scene files + a `scene-NN.ready` sentinel.
2. **Render, by chain group** — `videogen render` slices shots into
   chain groups (gating on `use_prev_last_frame_as_first`) and renders
   groups concurrently up to `VIDEOGEN_MAX_CONCURRENCY`. Within a chain
   group, still sequential because each shot's first_frame = the
   previous shot's last_frame.
3. **Per-clip review + retry** — every clip is scored by qwen3-vl-plus
   immediately after render. Below threshold → CLI auto-rewrites the
   prompt via qwen-text and re-renders (`S01-001-ver2.mp4`,
   `-ver3.mp4`, …). After `VIDEOGEN_MAX_RETRY` rounds, picks best-of-N
   and flags the shot for director rewrite (producer escalation).

## Why CLI + Skill, not MCP?

- **Video tasks are async (1–5 min/clip × 30 clips)** → polling, retries,
  OSS uploads, ffmpeg work all live in the CLI. The agent calls
  subcommands and reads JSON state — no in-flight blocking.
- **The hard part is creative direction**, not API plumbing. Skills carry the
  director's playbook (model choice per shot, pacing, prompt anchors,
  failure recovery).
- MCP would force the agent to hold state for 90 minutes per render. CLI
  is a better tool boundary.

## Quick start

### 1. Install

```bash
brew install ffmpeg python@3.11
python -m pip install -e .
cp .env.example .env  # fill in DASHSCOPE_API_KEY
videogen doctor

# One-time: pull the wrapped 山音 skills (screenwriter + director)
bash scripts/install-shanyin-skills.sh
```

### 2. Build a project

A **project** is one show (e.g. `wulin`). It owns a single `lore.md` and a
shared cast pool. Each **episode** (`episode-001`, `episode-002`, …) is a
single ~3-min film inside that show.

Drop your cast into per-character folders:

```
projects/wulin/
├── lore.md                            # project-level world bible
└── cast/                              # project mains (shared across episodes)
    ├── 佟掌柜/
    │   ├── cast.md                    # soul card (front-matter + body)
    │   ├── 佟掌柜.jpg                 # any portrait filename works
    │   └── 佟掌柜.mp3                 # any voice filename works
    ├── 钱夫人/
    │   ├── cast.md
    │   ├── 定妆照.webp
    │   └── voice.mp3
    └── 莫小贝/
        ├── cast.md
        └── 莫小贝.png
```

Anything inside one folder belongs to that character — no name-prefix
matching needed. If a character has multiple portraits, the CLI builds a
multi-pane reference grid **only from images in that one folder**.
Character grids never blend portraits across different folders.

Episode-specific NPCs live under `projects/wulin/episode-001/cast/`.

### 3. Drive from Claude Code or Qwen Code

```text
> /cast-init wulin 001
> /episode wulin 001 "明朝架空背景的搞笑武侠情景喜剧, 3 分钟. 佟掌柜和钱夫人结怨已深, 莫小贝要参加衡山派接任仪式..."
```

`/episode` first asks you to pick a **mode** (`drama` default vs
`narration`). You can pre-pick via flag:

```text
> /episode wulin 001 "..." --mode=narration       # 10-min recap style
> /episode wulin 001 "..." --mode=drama --vfx     # full short with VFX gate
```

The director skill writes
`projects/wulin/episode-001/{script.md, storyboard.json}`, shows you the
storyboard table for sign-off, then renders + stitches into
`projects/wulin/episode-001/final/wulin-episode-001.mp4`. In narration
mode each `role: "narration"` shot also gets a TTS voiceover muxed onto
its clip before stitching.

### 4. Re-roll a shot

```text
> /retry wulin 001 S02-004
```

Or by hand (full re-render including review loop):

```bash
videogen render --project wulin --episode 001 --shot S02-004 \
                --force --reset-attempts
```

Just re-score an existing clip without re-rendering:

```bash
videogen review --project wulin --episode 001 --shot S02-004 [--ver 2]
```

### 5. Inspect the parallel render plan

```bash
videogen render-graph --project wulin --episode 001
```

Shows how the storyboard slices into chain groups. Each group runs in
parallel up to `VIDEOGEN_MAX_CONCURRENCY`. If you see one giant chain,
push back to the director — the first shot of every scene should set
`use_prev_last_frame_as_first: false`.

## Project layout

```
videoGen/
├── pyproject.toml             # Python deps
├── .env.example
├── AGENTS.md / CLAUDE.md / QWEN.md
├── api-references/dashscope/  # Wan 2.7 + HappyHorse 1.0 + qwen API docs
├── scripts/
│   └── install-shanyin-skills.sh   # one-time: pull wrapped 山音 skills
├── .claude/
│   ├── skills/
│   │   ├── screenwriter/      # wraps references/shanyin-screenwriting
│   │   ├── video-director/    # wraps references/shanyin-director
│   │   ├── vfx-reviewer/      # opt-in pre-render gate
│   │   └── video-reviewer/    # post-render qwen-vl scoring
│   └── commands/              # /episode /scene-write /scene-direct /render /review /retry
├── .qwen/commands/            # mirror for Qwen Code (TOML)
├── src/videogen/
│   ├── cli.py                 # Typer entry — `videogen`
│   ├── config.py              # env + region routing
│   ├── cast.py                # ./cast → cast.json
│   ├── upload.py              # local file → oss:// URL
│   ├── providers/             # Wan / HappyHorse adapters (submit + wait + req shape)
│   ├── review.py              # qwen3-vl-plus per-clip scoring
│   ├── rewrite.py             # qwen-text auto prompt rewrite
│   ├── scene.py               # per-scene scaffold / ready / compile
│   ├── ffmpeg.py              # frame extraction + concat + audio mux
│   ├── tts.py                 # qwen3-tts-flash narration (narration mode)
│   ├── storyboard.py          # Pydantic schema (single source of truth)
│   ├── render.py              # chain-DAG parallel render + review loop
│   └── state.py               # per-episode JSON
├── projects/<project>/        # one folder per show
│   ├── lore.md                # project-level world bible
│   ├── cast/<name>/           # project mains (shared across episodes)
│   └── <episode>/             # one folder per episode (episode-001, ...)
│       ├── scenes/scene-NN.{md,ready,json}   # editor↔director per-scene pipeline
│       ├── script.md / storyboard.json       # merged from scenes/*
│       ├── cast.json + cast/<npc>/           # per-episode cast
│       ├── clips/<id>-verN.mp4               # versioned attempts
│       ├── clips/<id>.mp4                    # winner copy (used by stitch)
│       ├── frames/<id>-verN_last.png
│       ├── reviews/<id>-verN.json            # {score, breakdown, critique}
│       ├── shots_state.json                  # attempts[] + winner_version
│       ├── needs_director_rewrite.json       # only when render exits 3
│       └── final/  logs/
└── Makefile
```

## Shot-by-shot model strategy (TL;DR)

The director writes the **kind**, not a vendor model name. The active
provider maps it to its concrete model at render time.

| Need | Kind | Wan 2.7 model | HappyHorse 1.0 model | Notes |
|---|---|---|---|---|
| Dialog with named characters | `r2v` | `wan2.7-r2v` | `happyhorse-1.0-r2v` | Wan adds reference_voice + first_frame chain bridging; HappyHorse takes only reference_image |
| Establishing/no-character | `t2v` | `wan2.7-t2v-2026-04-25` | `happyhorse-1.0-t2v` | up to 15s |
| Visual transition only | `i2v` | `wan2.7-i2v-2026-04-25` | `happyhorse-1.0-i2v` | first_frame + last_frame chaining |

**Continuity trick** (Wan path): every shot's prompt is paired with
`first_frame = last_frame_of_previous_shot.png` (extracted by ffmpeg),
so successive shots visually flow. Wan r2v even lets you stack
reference_image + first_frame so you keep both character identity AND
scene continuity. HappyHorse r2v can't do this — when a chained `r2v`
shot is requested the renderer **auto-demotes** it to `i2v` (drops the
cast images, keeps the chain).

**Default each shot to the model maximum (15s).** A 3-min video is ~12
shots not 22 — fewer cuts, fewer identity drifts, fewer API calls. The
schema auto-clamps duration to the kind ceiling and the active provider
clamps to its own floor (Wan 2s, HappyHorse 3s).

## Budget gate

Before every full render the agent runs:

```bash
videogen storyboard estimate --project <id> --episode <ep>
```

This prints shots, total duration, wall-clock estimate, and verdict. If
total > `VIDEOGEN_LONG_CONFIRM_S` (default 180s = 3 min) the CLI exits 2 and
the agent must explicitly confirm with the user before passing `--yes` to
`render`. Tweak the threshold in `.env`.

## Debugging

See [`DEBUGGING.md`](./DEBUGGING.md).

## Cost note

Both Wan 2.7 and HappyHorse 1.0 are billed by output seconds × resolution.
A 3-min 720p video with ~22 shots typically costs around the same as
3 minutes of single-shot 720p generation. Re-rolls double the bill, so use `candidates: 1` for fillers and
`2-4` only for hero shots.

The per-clip review (qwen3-vl-plus) and auto-rewriter (qwen-plus) add
modest token cost per shot. Disable for cheap iteration:

```bash
videogen render --project <p> --episode <e> --no-review
# or
videogen render --project <p> --episode <e> --no-auto-rewrite
```

Or set `VIDEOGEN_REVIEW_MODEL=` (empty) / `VIDEOGEN_REWRITE_MODEL=` in
`.env` to disable globally.
