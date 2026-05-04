# videoGen — Long-form AI Video Director

Generate **3–10 minute** AI videos with consistent characters and scene
continuity, driven by **Claude Code** or **Qwen Code** as the directing brain
on top of **Wan 2.7** (Alibaba DashScope).

> "像抽卡一样写视频" — type a premise, get a screenplay → storyboard → 35-shot
> finished mp4. Re-roll any shot, retry any scene, swap any actor.

## How the pieces fit

```
┌─────────────────────────────────────────────────────────────┐
│  Claude Code / Qwen Code  (LLM director)                     │
│  ├── Skill: video-director  →  rules, prompt patterns        │
│  └── Slash commands  →  /cast-init  /storyboard  /render     │
└──────────────┬──────────────────────────────────────────────┘
               │ shell calls, JSON in / JSON out
               ▼
┌─────────────────────────────────────────────────────────────┐
│  videogen CLI  (Python · deterministic engine)               │
│  cast    →  scan ./cast, OSS upload, cast.json               │
│  wan     →  submit + poll t2v / i2v / r2v / videoedit        │
│  ffmpeg  →  last-frame extraction, concat, crossfade         │
│  state   →  per-project JSON, resumable                      │
└──────────────┬──────────────────────────────────────────────┘
               ▼
       Wan API (DashScope) + ffmpeg + OSS
```

## Why CLI + Skill, not MCP?

- **Wan tasks are async (1–5 min/clip × 30 clips)** → polling, retries, OSS
  uploads, ffmpeg work all live in the CLI. The agent calls subcommands and
  reads JSON state — no in-flight blocking.
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
```

### 2. Drop your cast into `./cast/`

```
cast/
├── 佟掌柜.jpg
├── 佟掌柜.mp3
├── 钱夫人.jpg
├── 钱夫人.mp3
├── 莫小贝.jpg
└── 莫小贝.mp3
```

Pair stem `<name>.{jpg,png}` with `<name>.{mp3,wav}`. Image-only is OK (the
character can appear but won't speak).

### 3. Drive from Claude Code or Qwen Code

```text
> /cast-init wulin
> /storyboard wulin "明朝架空背景的搞笑武侠情景喜剧, 3 分钟. 佟掌柜和钱夫人结怨已深, 莫小贝要参加衡山派接任仪式..."
> /render wulin
```

The director skill writes `projects/wulin/{script.md, storyboard.json}`,
shows you the storyboard table for sign-off, then renders + stitches into
`projects/wulin/final/wulin.mp4`.

### 4. Re-roll a shot

```text
> /retry wulin S02-004
```

Or by hand:

```bash
videogen render --project wulin --shot S02-004 --force
```

## Project layout

```
videoGen/
├── pyproject.toml             # Python deps
├── .env.example
├── AGENTS.md / CLAUDE.md / QWEN.md
├── api-references/wan/        # Wan 2.7 API docs (provided)
├── .claude/
│   ├── skills/video-director/ SKILL.md     # the director's brain
│   └── commands/              # /cast-init /storyboard /render /retry
├── .qwen/commands/            # mirror for Qwen Code (TOML)
├── src/videogen/
│   ├── cli.py                 # Typer entry — `videogen`
│   ├── config.py              # env + region routing
│   ├── cast.py                # ./cast → cast.json
│   ├── upload.py              # local file → oss:// URL
│   ├── wan.py                 # submit + wait
│   ├── ffmpeg.py              # frame extraction + concat
│   ├── storyboard.py          # Pydantic schema (single source of truth)
│   ├── render.py              # the render pipeline
│   └── state.py               # per-project JSON
├── cast/                      # users put portraits + voices here
├── projects/<id>/             # everything generated lives here
└── Makefile
```

## Shot-by-shot model strategy (TL;DR)

| Need | Model | Notes |
|---|---|---|
| Dialog with named characters | `wan2.7-r2v` | reference_image + reference_voice per character |
| Establishing/no-character | `wan2.7-t2v-2026-04-25` | up to 15s |
| Visual transition only | `wan2.7-i2v-2026-04-25` | first_frame + last_frame chaining |
| Edit existing clip | `wan2.7-videoedit` | not used in the default pipeline |

**Continuity trick**: every shot's prompt is paired with `first_frame =
last_frame_of_previous_shot.png` (extracted by ffmpeg), so successive shots
visually flow. r2v even lets you stack reference_image + first_frame so you
keep both character identity and scene continuity.

## Debugging

See [`DEBUGGING.md`](./DEBUGGING.md).

## Cost note

Wan 2.7 is billed by output seconds × resolution. A 3-min 720p video with
~22 shots typically costs around the same as 3 minutes of single-shot 720p
generation. Re-rolls double the bill, so use `candidates: 1` for fillers and
`2-4` only for hero shots.
