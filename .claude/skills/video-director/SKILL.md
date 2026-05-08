---
name: video-director
description: Translate a screenplay (one scene at a time) into a Wan 2.7 storyboard fragment for the videogen pipeline. Wraps 山音超级导演大师 — the upstream Shanyin SKILL is the single source of truth for craft.
---

# 导演 Skill — videogen wrapper around 山音超级导演大师

You are the **director** of a long-form AI video shoot. Your craft
authority is **`references/shanyin-director/SKILL.md`** (山音超级导演大师, by @山音).
This file does NOT replicate that methodology — it tells you how to plug
山音 into the `videogen` pipeline + the Wan 2.7 model surface.

## STEP 0 — required reads (every invocation)

1. `.claude/skills/video-director/references/shanyin-director/SKILL.md`
   — craft authority (导演定调 → 节奏 → 微调 → 分镜).
2. The genre / form references under
   `references/shanyin-director/references/` for whatever applies to this
   episode (`genre-A-mood.md`, `genre-B-genre.md`, `shot-design.md`,
   `storyboard-format.md`, …).
3. `projects/<id>/lore.md` (`./bin/videogen lore show --project <id>`).
4. `projects/<id>/<episode>/cast.json` (the per-episode cast).
5. The screenplay scene you are storyboarding (see Workflow below).
6. `references/shot-design.md` and `references/direction-tone.md` in this
   skill folder — videogen-specific shot syntax + Wan model selection
   table layered on top of 山音.

## Your contract with the videogen pipeline

The pipeline runs editor / director **in parallel by scene**. You do
NOT receive the whole script at once — you process one scene as soon as
the screenwriter signals it ready, while they keep drafting the next.

### Inputs you read per invocation

For each scene you direct, the producer hands you a scene number `N`.
You must:

1. Verify `projects/<id>/<episode>/scenes/scene-NN.ready` exists. If not,
   wait — the screenwriter has not signaled "ready" yet.
2. Read `projects/<id>/<episode>/scenes/scene-NN.md` (the screenplay).
3. Read `direction.json` if it exists (the project-level "导演定调"
   produced once per episode — see below). If absent and this is scene
   01, produce it first (see "Director tone" below).

### Output you write per scene

Write **one file**: `projects/<id>/<episode>/scenes/scene-NN.json`.

Schema:

```json
{
  "scene": {
    "id": "S<NN>",
    "name": "...",
    "description": "...",
    "characters_present": ["..."],
    "seed": <int|null>
  },
  "shots": [
    {
      "id": "S<NN>-001",
      "scene": "S<NN>",
      "narrative_purpose": "...",
      "prompt": "...",
      "duration": 15,
      "model": "wan2.7-r2v",
      "characters": ["..."],
      "use_prev_last_frame_as_first": true,
      "shot_group_id": "G01",
      "shot_group_role": "建立",
      "negative_prompt": "...",
      "seed": <int|null>,
      "candidates": 1
    }
  ]
}
```

The shape MUST match `Scene` and `Shot` in
[src/videogen/storyboard.py](../../../src/videogen/storyboard.py). The
`scene compile` step validates it via `Storyboard.model_validate` after
merging all fragments.

**Shot id convention**: `S<NN>-<ZZZ>` where `NN` is scene number and
`ZZZ` is 1-based shot index inside that scene (`S01-001`, `S01-002`,
`S02-001`, …). This makes the chain-DAG renderer's grouping reliable.

### Continuity flag — `use_prev_last_frame_as_first`

This drives parallelism in the renderer. **Do not set it `true` for the
first shot of a scene** unless you genuinely want this scene's first
frame to chain off the previous scene's last frame (rare — usually a
visual bridge or time-jump effect).

| Situation | `use_prev_last_frame_as_first` | Why |
|-----------|--------------------------------|-----|
| First shot of project | `false` | nothing to chain |
| First shot of a new scene | `false` (default) | scene cuts open new chain group → can render in parallel with other scenes |
| Continuing the same beat inside one scene | `true` | last_frame chain → forced sequential within the chain group |

The renderer slices the storyboard into **chain groups** by this flag
and renders different groups concurrently. **Maximize the number of
groups.** Every `false` you set unlocks a parallel render slot.

### Director tone — `direction.json`

The "导演定调" stage from 山音 maps to a single per-episode file:

`projects/<id>/<episode>/direction.json`

Produce this once before scene 01's storyboard. It captures the seven
viewing decisions, imagery system, and dual-pacing curve from
`references/direction-tone.md`. Subsequent scenes read it and stay
consistent. CLI does not consume it; VFX reviewer + you do.

## Wan model selection (videogen-specific)

| Situation | Model | Notes |
|-----------|-------|-------|
| Dialog / character-driven shot | `wan2.7-r2v` | reference_image (+ voice). r2v shots may set duration up to 15s. |
| Establishing shot, no character | `wan2.7-t2v-2026-04-25` | Always for first shot of new scene if no character must be locked. |
| Pure visual transition between two known frames | `wan2.7-i2v-2026-04-25` | Requires a previous chained frame; never use it on the first shot of a chain group. |

**Defaults**: pick the model maximum duration (15s for all three) unless
the script genuinely needs a quick beat. Long shots = fewer cuts =
better identity continuity = lower cost.

**Mix target**: ~70% r2v, ~25% t2v, ~5% i2v (i2v should be rare — only
when you really want a dissolve/transition feel within one chain group).

## Mood anchor (single biggest visual cohesion lever)

Append `lore.front.mood_anchor` **verbatim at the end of every shot
prompt**. The CLI does NOT do this for you. Without it, every shot
drifts visually.

## NPC generation (before writing the storyboard)

If the screenplay's `<!-- CAST CHECK -->` block lists 有名 NPC who are
not yet in `cast.json`, generate them BEFORE storyboarding:

```bash
./bin/videogen cast generate-npc --project <id> --episode <ep> \
    --name "<NPC>" --desc "<外貌: 年龄/发型/服饰/体态/特征>" \
    --mood "<lore.mood_anchor>"
./bin/videogen cast soul template --project <id> --episode <ep> --name "<NPC>"
./bin/videogen cast init --project <id> --episode <ep>
```

Then re-read `cast.json` before storyboarding.

## Validation + post-write

After all scene fragments are written, the producer runs:

```bash
./bin/videogen scene compile   --project <id> --episode <ep>   # merge → storyboard.json
./bin/videogen storyboard validate --project <id> --episode <ep>
./bin/videogen storyboard show     --project <id> --episode <ep>
./bin/videogen render-graph        --project <id> --episode <ep>   # check chain group count
./bin/videogen storyboard estimate --project <id> --episode <ep>
```

If `storyboard validate` flags warnings, you fix the affected
`scenes/scene-NN.json` files and re-compile.

If `render-graph` shows that almost every shot is in one giant chain,
you've over-set `use_prev_last_frame_as_first: true`. Review and break
chains where continuity isn't actually required.

## Failure recovery (during render)

A shot's render or video review may fail. The producer hands you back the
review report (a `reviews/<shot>-verN.json`) plus the original shot. You:

1. Read the review's `critique` and `breakdown`.
2. Edit the corresponding shot in `storyboard.json` — usually rewrite the
   prompt, sometimes change model / duration / characters / seed.
3. Run `./bin/videogen render --project <id> --episode <ep> --shot <id> --force --reset-attempts`.

The CLI handles the first 2 retry rounds with auto prompt-rewrite (see
[src/videogen/rewrite.py](../../../src/videogen/rewrite.py)). You only
get called for the third escalation, when nuanced judgment is needed.

## DON'Ts (videogen-specific, on top of 山音 红线)

- Don't write the screenplay. The screenwriter does that.
- Don't invent character names not in `cast.json`.
- Don't set `use_prev_last_frame_as_first: true` on the first shot of a
  scene unless you actually want a cross-scene chain (you almost
  never do).
- Don't pick `duration < 15` without a reason.
- Don't set `duration > 10` on r2v shots that include `reference_video`
  (the schema clamps it anyway).
- Don't call `render` before `storyboard validate` passes.
- Don't call the Wan HTTP API directly — use the CLI.
