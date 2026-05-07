---
description: Director — compile script.md into storyboard.json (scenes + shots) for one episode.
argument-hint: <project_id> <episode_id>
---

Project: $1, Episode: $2

Activate the `video-director` skill. You are the DIRECTOR — you translate
the screenwriter's script into a technical storyboard.

### Prerequisites

1. Verify `projects/$1/$2/script.md` exists (the screenwriter must run first).
2. Read `projects/$1/$2/cast.json` — these are your available actors.
3. Run `./bin/videogen lore show --project $1` — note `mood_anchor`.
4. Run `./bin/videogen cast soul show --project $1 --episode $2` — read every soul.

### NPC check

Scan the `<!-- CAST CHECK -->` block at the end of `script.md`. For every
"有名NPC" listed that is NOT in `cast.json`, default to the **episode**
tier (so they don't pollute other episodes):

```bash
./bin/videogen cast generate-npc --project $1 --episode $2 \
  --name "<NPC名>" \
  --desc "<外貌描述>" \
  --mood "<lore.mood_anchor>"
./bin/videogen cast soul template --project $1 --episode $2 --name "<NPC名>"
```

(If the NPC will recur across multiple episodes, drop the `--episode` flag
to put them under `projects/$1/cast/` instead.)

After generating all NPCs, re-run
`./bin/videogen cast init --project $1 --episode $2`.

### Scene planning

First define `scenes[]` — one entry per location+time+situation:
- `id`, `name`, detailed `description` (50–150 chars physical detail).
- `characters_present` (all chars who appear in that scene).
- `seed` (shared by all shots in scene; different per scene).

### Shot compilation

Write `shots[]` per the director skill rules:
- Apply 续接黄金五条 (continuity rules 1–6).
- Weave `scene.description` keywords into each prompt.
- Append `lore.mood_anchor` verbatim to every prompt.
- Embed all dialog from script.md into shot prompts.
- Ensure protagonist stays in frame for action sequences.

### Validate

```bash
./bin/videogen storyboard validate --project $1 --episode $2
./bin/videogen storyboard show     --project $1 --episode $2
```

Fix any validation errors. Verify the Anchor column shows ✓ on every shot.

### Estimate

```bash
./bin/videogen storyboard estimate --project $1 --episode $2
```

Surface the numbers (shots, total duration, wall-clock). If exit code 2
(over `VIDEOGEN_LONG_CONFIRM_S`), flag it for the orchestrator.

### Deliver

Show the storyboard table to the user. Ready for VFX review.
