# AGENTS.md — entry point for any agentic CLI working in this repo

This repo is a **director's toolbox** for generating long-form (3–10 min) AI
videos with consistent characters on Alibaba DashScope. Two video model
families are supported via a provider abstraction:

- **HappyHorse 1.0** (default) — `happyhorse-1.0-{t2v,i2v,r2v}`. Fewer
 features than Wan but newer.
- **Wan 2.7** — `wan2.7-{t2v-2026-04-25,i2v-2026-04-25,r2v}`. Richer
 features (reference_voice, first_frame chain-bridging in r2v,
 negative_prompt, prompt_extend).

Episodes can be produced in either of two **modes** (chosen by the user
at the very start of `/episode`):

- **drama** (短剧, default) — every shot is a long self-contained clip
 driven by dialog + action. Today's behaviour. Use for 2–5 min original
 shorts.
- **narration** (旁白解说, "10 分钟带你看完 XX") — screenwriter writes
 节拍 (mixed 旁白 + 对白); 旁白 beats become short (3–6s) shots whose
 audio is **stripped and replaced** by `cosyvoice-v3-flash` voiceover via
 `ffmpeg.mux_audio`. 对白 beats stay as today's drama shots. Maximises
 parallelism (every 旁白 shot is its own chain group) and works around
 the video models' lack of long-form cohesion.

Storyboards are written **provider-agnostically** — each shot declares a
generic `kind` (`t2v` / `i2v` / `r2v`) and the active provider maps it
to a concrete model name at render time. Provider resolution order:
`videogen render --provider` flag → `Storyboard.provider` (per-episode,
set by `scene compile --provider`) → `VIDEOGEN_VIDEO_PROVIDER` env var
→ built-in default `happyhorse`. See `src/videogen/providers/` for the
implementation and `.claude/skills/video-director/SKILL.md` § "Provider
capability table" for behavioural differences directors must know.

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
| **Video Reviewer** *(new)* | `.claude/skills/video-reviewer/SKILL.md` | Per-clip 0-10 scoring on 6 axes (logic / proportion / physics / style / cast_match / dialog_attribution) via qwen3-vl-plus, with cast portraits attached to the multimodal call so face-swap and 台词错位 are caught; drives auto-rewrite + escalation. | `reviews/<shot>-verN.json` |
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
├── movie-set/                         ← project-shared 布景 (sitcom rooms etc.)
│   └── <set_name>/{set.md,*.png}
├── props/                             ← project-shared 关键道具 (recurring hero items)
│   └── <prop_name>/{prop.md,*.png}    (one folder per state: 红包-完整 / 红包-起皱 …)
├── bgm/                               ← project-shared BGM library (optional)
│   └── <track-name>.{mp3,wav,m4a,flac,ogg,aac}
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
    ├── cast/                          ← episode-only cast (NPCs OR costume overrides via `cast fork`)
    │   └── <npc_name>/{cast.md,*.png}
    ├── cast_built/                    ← ASCII-renamed singletons + grids
    ├── movie_set.json                 ← built per episode (project + episode sets merged)
    ├── movie-set/                     ← episode-only locations (one-off sets)
    │   └── <set_name>/{set.md,*.png}
    ├── movie_set_built/               ← ASCII-renamed singletons + grids (sets)
    ├── props.json                     ← built per episode (project + episode props merged)
    ├── props/                         ← episode-only props (one-off OR state override)
    │   └── <prop_name>/{prop.md,*.png}
    ├── props_built/                   ← ASCII-renamed singletons + grids (props)
    ├── bgm/                           ← episode-only BGM (optional; overrides
    │   └── <track-name>.{mp3,wav,...}    project tier on name collision)
    ├── clips/
    │   ├── S01-001-ver1.mp4           ← versioned attempts
    │   ├── S01-001-ver2.mp4
    │   └── S01-001.mp4                ← copy of the winning version
    ├── frames/  S01-001-ver1_last.png ← per-attempt last frames
    ├── reviews/
    │   ├── S01-001-ver1.json          ← {score, breakdown, critique, verdict}
    │   └── escalation-S01-001.md      ← only when needs_director_rewrite=true
    ├── final/
    ├── logs/
    │   └── model_calls.jsonl          ← every model call (video / review /
    │                                    rewrite / t2i): request + response
    │                                    + duration + shot/version context
    ├── shots_state.json               ← attempts[] + winner_version per shot
    ├── needs_director_rewrite.json    ← present only when render exits 3
    └── state.json
```

## Always-on rules

1. Read the relevant skill file before doing any work in that role.
 Screenwriter / director SKILL.md files are *wrappers* — also read the
 inner Shanyin SKILL each cites.
2. Never call the DashScope video / qwen HTTP API yourself — go through
 `videogen` subcommands (`render`, `review`, `task ...`). The provider
 layer (`src/videogen/providers/`) is the only code allowed to talk to
 DashScope's video-synthesis endpoint.
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
 when the script genuinely needs a quick beat. Per-provider duration
 *floor* differs (Wan 2s, HappyHorse 3s) — the provider clamps and warns.
11. State of every episode lives in `projects/<id>/<episode>/`. Treat it
    as the source of truth.
12. Episode IDs are normalized: pass `--episode 001` → CLI maps to
    folder `episode-001`. Bare `--episode episode-001` also accepted.
13. **Per-clip review is on by default**. To run a render without
    qwen-vl scoring, pass `--no-review` to `render`.
14. **Character consistency is the cast portrait's job, not the
    prompt's.** The director SKILL forbids 着装 / 发型 / 妆容 / 配饰 in
    shot prompts — those drift the model. Only **age** is required in
    every chain group's first character mention (`28岁的陆辰` etc.). If
    a costume genuinely differs for one episode, fork the cast into the
    episode tier (`cast fork --regen ...`) — never solve it by writing
    "穿着 XXX" into the prompt.
15. **Scene consistency is the movie-set's job.** When two or more shots
    share a location, scaffold a 布景 folder
    (`projects/<id>/movie-set/<name>/` for sitcom-recurring rooms,
    `projects/<id>/<ep>/movie-set/<name>/` for one-offs) with a
    reference image, and set every applicable `Scene.set_id`. The
    renderer auto-attaches the set's image to every r2v shot in that
    scene's media[] — no need to repeat 客栈大堂 in shot prompts.
16. **One movie-set folder = one lighting state.** AI video models
    read the set reference image literally; reusing a 白天 set in a
    夜晚 shot makes the model average the two lightings into a muddy
    drift. Split the SAME location across folders by 时段 (白天/黄昏/
    夜晚/凌晨), 季节 (春/夏/秋/冬), 色调 (冷/暖/中性), 天气 (晴/雨/雪).
    Naming convention: `<location>-<discriminator>` (e.g.
    `同福客栈大堂-白天`, `同福客栈大堂-夜晚`). Use `Shot.set_id` for
    per-shot overrides when one scene's beats span multiple lighting
    states (common in narration mode); the storyboard linter enforces
    "every r2v shot in one chain group resolves to the same set" — if
    you see that warning, split the chain at the boundary.
17. **Key-prop consistency is the prop reference image's job.** Recurring
    objects (红包, 戒指, 钥匙, 玩具熊, 笔记本…) drift exactly like cast
    and locations do. For any object that appears in 2+ shots OR is a
    story-critical hero item, scaffold a folder
    (`projects/<id>/props/<name>/` for project-shared, `<ep>/props/<name>/`
    for episode-only) with one reference image, then list it in
    `Shot.props: ["<name>", ...]` on every r2v shot it appears in. The
    renderer auto-attaches the prop's image to media[] after cast and set.
    The director SKILL forbids re-describing the prop's 材质 / 颜色 /
    形状 in the prompt — only the *action* and at most a single state
    word ("起皱的红包"). State changes (完整 → 起皱 → 撕碎) are
    SEPARATE folders (`<prop>-<state>` naming convention), never multiple
    state images in one folder. Skip props on `t2v` / `i2v` shots — they
    have no media[] slot and the linter warns.
18. **BGM lives outside the model.** Drop audio files into
    `projects/<id>/bgm/` (project-shared) or
    `projects/<id>/<ep>/bgm/` (episode-only). When such a folder is
    present, `/episode` stops at **GATE 0.5** and asks the user:
    (1) how to use the BGM — `off` / `global` (one track for the
    whole video) / `scene` (per-scene via `Scene.bgm_track`) — and
    (2) whether to **forbid the video model from generating its own
    BGM** (default on, prevents two music tracks fighting each
    other). When forbidden, the renderer auto-appends a no-music
    directive to every shot prompt (and to `negative_prompt` on Wan).
    Stitch mixes the chosen track(s) underneath the dialog audio at
    `Storyboard.bgm.volume` (default 0.25) with fade-in/-out.
    Director picks the per-scene track based on the scene's
    emotional beat (煽情 → 钢琴慢板, 惊悚 → 低频持续音, 轻喜 →
    拨弦小调) and writes it into `Scene.bgm_track` in
    `scenes/scene-NN.json`.

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
- `/episode <project> <episode> "<premise>" [--vfx] [--provider=happyhorse|wan] [--mode=drama|narration]` —
 autopilot: per-scene editor↔director parallel → render (parallel +
 per-clip review + auto-rewrite + escalation) → stitch. `--vfx` opts
 into pre-render VFX review (default: bypassed). `--provider` pins the
 video model family for this episode (default: env `VIDEOGEN_VIDEO_PROVIDER`,
 falling back to `happyhorse`). `--mode` pins the episode mode; if
 absent the producer stops at GATE 0 and asks the user (drama vs
 narration). When a `bgm/` folder is detected under either tier, the
 producer additionally stops at GATE 0.5 to ask how to use the BGM
 (off / global / scene) and whether to forbid the model's own BGM.

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

# Cast (per episode — merges project mains + episode NPCs / overrides)
./bin/videogen cast init       --project <p> --episode <e>
./bin/videogen cast ls         --project <p> --episode <e>
./bin/videogen cast soul show  --project <p> --episode <e>
./bin/videogen cast soul template --project <p> [--episode <e>] --name <NAME>
./bin/videogen cast generate-npc  --project <p> [--episode <e>] \
        --name <NAME> --desc "<appearance>" [--mood "<anchor>"]
# Costume / appearance override for ONE episode only — copies the
# project cast folder into the episode tier and (optionally) regenerates
# the portrait via t2i with the new look. The rest of the project stays
# unchanged.
./bin/videogen cast fork       --project <p> --episode <e> --name <NAME> \
        [--regen "<new appearance>" --mood "<anchor>"] [--drop-portraits] [--force]

# Movie sets / 布景 (per episode — same two-tier model as cast)
./bin/videogen set init        --project <p> --episode <e>
./bin/videogen set ls          --project <p> --episode <e>
./bin/videogen set scaffold    --project <p> [--episode <e>] --name "<set name>"
./bin/videogen set generate    --project <p> [--episode <e>] \
        --name "<set name>" --desc "<材质/布局/灯光/关键道具>" [--mood "<anchor>"]

# Key props / 关键道具 (per episode — same two-tier model as cast / set)
# State changes = separate folders: 红包-完整, 红包-起皱, 红包-撕碎
./bin/videogen prop init       --project <p> --episode <e>
./bin/videogen prop ls         --project <p> --episode <e>
./bin/videogen prop scaffold   --project <p> [--episode <e>] --name "<prop_name>[-<state>]"
./bin/videogen prop generate   --project <p> [--episode <e>] \
        --name "<prop name>" --desc "<材质/颜色/形状/关键细节>" [--mood "<anchor>"]

# BGM / 配乐 (drop audio files into projects/<p>/bgm/ or projects/<p>/<e>/bgm/)
./bin/videogen bgm ls          --project <p> --episode <e>                # list tracks
./bin/videogen bgm discover    --project <p> --episode <e> [--json]       # producer probe (exit 2 = no bgm)
./bin/videogen bgm configure   --project <p> --episode <e> \
        --mode off|global|scene \
        [--forbid-model-bgm/--allow-model-bgm] \
        [--track <stem>] [--volume 0.25] [--fade-in 0.5] [--fade-out 1.0] \
        [--disable]                                                       # writes storyboard.bgm

# Per-scene parallel pipeline (Zone 1)
./bin/videogen scene scaffold --project <p> --episode <e> --num <N> \
        [--mode drama|narration]                                         # template (narration → 节拍式)
./bin/videogen scene ready    --project <p> --episode <e> --num <N>      # editor signal
./bin/videogen scene status   --project <p> --episode <e>                # progress
./bin/videogen scene compile  --project <p> --episode <e> \
        [--provider happyhorse|wan] \
        [--mode drama|narration] \
        [--narrator-voice longanyang]                                    # merge → script.md + storyboard.json (writes provider+mode+narrator_voice)

# Narration TTS (auto-invoked by render when storyboard.mode=narration; CLI is for previews).
# Backend is picked by model name prefix:
#   cosyvoice-* (default) → /services/audio/tts/SpeechSynthesizer, native rate, 仅北京
#   qwen*-tts*           → /services/aigc/multimodal-generation/generation, ffmpeg atempo
./bin/videogen tts synth --text "..." --out path.wav \
        [--voice longanyang] [--language Chinese] [--model cosyvoice-v3-flash]

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
        [--concurrency 4] [--provider happyhorse|wan]
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
`Storyboard` Pydantic models). Shots use `kind: t2v|i2v|r2v` (not
vendor-specific model names); legacy `model: "wan2.7-*"` strings are
auto-migrated on load. `Storyboard.provider` pins the model family for
the episode. `Storyboard.mode` (`drama` | `narration`) pins the
production mode; narration-mode storyboards may carry shots with
`role: "narration"` + `narration_text` (drama-mode storyboards reject
those at validate-time). Per-shot review state: see
`src/videogen/render.py` (`_empty_shot_record` for the `attempts[]` +
`winner_version` schema). Provider implementations:
`src/videogen/providers/{base,wan,happyhorse}.py`. Narration TTS lives
in `src/videogen/tts.py` and supports two backends, dispatched by model
name prefix: `cosyvoice-*` (default, `/services/audio/tts/SpeechSynthesizer`,
native `rate`, **仅北京地域**) and `qwen*-tts*` (legacy,
`/services/aigc/multimodal-generation/generation`, ffmpeg `atempo`
post-process). Switch by setting `VIDEOGEN_NARRATOR_TTS_MODEL` (and a
matching `VIDEOGEN_NARRATOR_VOICE` — voice taxonomy differs between
backends).

`Scene.set_id` (optional string) — references a movie-set folder name.
At render time, the active provider appends that set's reference image
to every r2v shot in the scene's `media[]`, locking the location's
appearance the same way cast portraits lock characters. Per-shot
override via `Shot.set_id` (use `null` to inherit, `""` to opt-out,
any other string to override) — common in narration mode where one
logical scene legitimately spans multiple lighting states. The
storyboard linter enforces "all r2v shots within one chain group
resolve to the same set_id" (灯光统一铁律). Movie-set schema +
discovery: `src/videogen/movie_set.py`. **One folder = one lighting
state**: split same-location-different-time into separate folders
(`同福客栈大堂-白天`, `同福客栈大堂-夜晚`).

`Shot.props` (`list[str]`, default `[]`) — names of key props
(关键道具) featured in the shot. Each name must match a folder under
`projects/<id>/props/<name>/` or `projects/<id>/<ep>/props/<name>/`
(case-sensitive). At render time the active provider appends each
prop's reference image to the r2v shot's `media[]` *after* cast
portraits and *after* the set image; HappyHorse drops props first
when its 9-image cap is hit (warns). `Scene.props_present` mirrors
`characters_present` for recall — the linter warns when a shot
references a prop the scene didn't declare. **One folder = one
narrative state** (完整 / 起皱 / 撕碎 → three folders, named
`<prop>-<state>`). Props on `t2v` / `i2v` shots are a no-op (linter
warns) — the kind has no `media[reference_image]` slot. Prop schema +
discovery: `src/videogen/prop.py`.

`Storyboard.bgm` (`BGMConfig`, optional) — background music config.
Fields: `enabled` (master switch), `mode` (`off` | `global` | `scene`),
`forbid_model_bgm` (inject "no music" into shot prompts to prevent the
video model from generating competing BGM), `track` (filename stem
under `bgm/`, used in `global` mode), `volume` (0–1, default 0.25),
`fade_in_s` / `fade_out_s`. The schema raises on `mode='global'` without
`track`, and on `mode='scene'` when no `Scene.bgm_track` is tagged.
Per-scene: `Scene.bgm_track` (string, optional) — track name used when
the storyboard is in `scene` mode; null = silence under that scene's
clips. BGM discovery + path resolution: `src/videogen/bgm.py`. Stitch
mixes BGM via `ffmpeg.mix_bgm` — original dialog/TTS audio is preserved
and the BGM is attenuated, looped, and fitted to the video duration.

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

Provider:

| Var | Default | Meaning |
|-----|---------|---------|
| `VIDEOGEN_VIDEO_PROVIDER` | `happyhorse` | `happyhorse` \| `wan`. Workspace-wide default. Per-episode override: `Storyboard.provider` (set by `scene compile --provider`). Per-run override: `videogen render --provider`. See `src/videogen/providers/` and the director SKILL.md "Provider capability table". |

Narration mode TTS (only used when `Storyboard.mode == "narration"`):

| Var | Default | Meaning |
|-----|---------|---------|
| `VIDEOGEN_NARRATOR_TTS_MODEL` | `cosyvoice-v3-flash` | TTS model name. Backend is auto-picked by prefix: `cosyvoice-*` → CosyVoice (native `rate`, **仅北京地域**); `qwen*-tts*` → Qwen-TTS (ffmpeg `atempo` post-process). |
| `VIDEOGEN_NARRATOR_VOICE` | `longanyang` | Default voice — must match the chosen backend. CosyVoice voices e.g. `longanyang`/`longwan`/`longxiang` ([list](https://help.aliyun.com/zh/model-studio/cosyvoice-voice-list)); Qwen-TTS voices e.g. `Cherry`/`Ethan` ([list](https://help.aliyun.com/zh/model-studio/qwen-tts#bac280ddf5a1u)). Per-episode override: `Storyboard.narrator_voice` (set by `scene compile --narrator-voice`). Per-shot override: `Shot.narrator_voice`. |
| `VIDEOGEN_NARRATOR_SPEECH_RATE` | `1.2` | Speech speed (0.5–2.0). CosyVoice consumes natively; Qwen-TTS applies via ffmpeg `atempo`. |
| `VIDEOGEN_NARRATOR_LANGUAGE` | `Auto` | `Auto` or one of Chinese/English/German/Italian/Portuguese/Spanish/Japanese/Korean/French/Russian. Specifying improves pronunciation when content is single-language. On CosyVoice, mapped to `language_hints` (zh/en/...); `Italian`/`Spanish` are not in CosyVoice's hint list and fall back to auto-detect. |
