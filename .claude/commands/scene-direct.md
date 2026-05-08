---
description: Drive the director to compile a single scene fragment (scenes/scene-NN.json) from its corresponding scene-NN.md. Use this to run the director on one scene at a time, in parallel with the screenwriter still drafting.
argument-hint: <project_id> <episode_id> <scene_num>
---

Project: $1
Episode: $2
Scene number: $3

Read `.claude/skills/video-director/SKILL.md` first, then act per its rules.

## Step 1 — wait until the screenwriter signals ready

If `projects/$1/$2/scenes/scene-NN.ready` does not exist, the
screenwriter has not finished drafting scene NN yet. Either:
- abort and ask the user to wait, or
- if you were specifically asked to run anyway, proceed but warn loudly.

## Step 2 — read context

Required reads BEFORE storyboarding (per the SKILL):
- `.claude/skills/video-director/SKILL.md`
- `.claude/skills/video-director/references/shanyin-director/SKILL.md`
- `projects/$1/lore.md`
- `projects/$1/$2/cast.json`
- `projects/$1/$2/direction.json` (if exists)
- `projects/$1/$2/scenes/scene-NN.md` (the scene you're directing)
- All earlier `projects/$1/$2/scenes/scene-*.json` (for visual / chain continuity)

## Step 3 — produce direction.json (only if missing AND scene == 1)

If `direction.json` doesn't exist and `$3 == 1`, write it first per
`references/direction-tone.md`. Subsequent scene direct invocations
read it and stay consistent.

## Step 4 — generate any missing NPCs

If the scene script references named characters not in cast.json, run:

```bash
./bin/videogen cast generate-npc --project $1 --episode $2 \
    --name "<NPC>" --desc "<外貌>" --mood "<lore.mood_anchor>"
./bin/videogen cast soul template --project $1 --episode $2 --name "<NPC>"
./bin/videogen cast init --project $1 --episode $2
```

## Step 5 — write `scenes/scene-NN.json`

Where NN is `$3` zero-padded. Schema:

```json
{
  "scene": { /* one Scene object */ },
  "shots": [ /* Shot objects, ids S<NN>-001, S<NN>-002, ... */ ]
}
```

Strict rules (most important):
- Every shot's `prompt` ends with `lore.mood_anchor` verbatim.
- Every shot has a concrete `narrative_purpose` (no platitudes).
- The first shot of this scene MUST have `use_prev_last_frame_as_first: false`.
  (This unlocks parallel rendering with other scenes.)
- Shot ids start with `S<NN>-` so chain-DAG slicing works.

## Step 6 — show status

```bash
./bin/videogen scene status --project $1 --episode $2
```

Post a one-line summary: "scene NN storyboarded (X shots, ~Ys total)".
