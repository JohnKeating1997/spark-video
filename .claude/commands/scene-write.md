---
description: Drive the screenwriter to draft a single scene file (scenes/scene-NN.md) and signal it ready. Use this for manual per-scene control or to redo one scene of an existing script.
argument-hint: <project_id> <episode_id> <scene_num> "<premise or note>"
---

Project: $1
Episode: $2
Scene number: $3
Premise / note: $4

Read `.claude/skills/screenwriter/SKILL.md` first, then act per its rules.

## Step 1 — scaffold

```bash
./bin/videogen scene scaffold --project $1 --episode $2 --num $3
```

(no-op if the file already exists)

## Step 2 — read context

Required reads BEFORE writing (per the SKILL):
- `.claude/skills/screenwriter/references/shanyin-screenwriting/SKILL.md`
- `projects/$1/lore.md` (`./bin/videogen lore show --project $1`)
- `projects/$1/$2/cast.json` + soul cards
- All earlier `projects/$1/$2/scenes/scene-*.md` (for narrative continuity)

## Step 3 — write `scenes/scene-NN.md`

Where NN is `$3` zero-padded to 2 digits. Strict 山音 format (see SKILL).

If `$3` is the LAST scene of the episode, also append the
`<!-- CAST CHECK -->` block.

## Step 4 — signal ready

```bash
./bin/videogen scene ready --project $1 --episode $2 --num $3
```

This touches `scenes/scene-NN.ready` so any director worker pollings the
folder knows scene NN is ready to storyboard.

## Step 5 — show status

```bash
./bin/videogen scene status --project $1 --episode $2
```

Then post a one-line summary: "scene NN drafted (~XX s)".
