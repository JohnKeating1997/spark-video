---
description: Screenwriter — turn a premise into a polished script.md for one episode.
argument-hint: <project_id> <episode_id> "<premise>"
---

Project: $1, Episode: $2
Premise: $3

Activate the `screenwriter` skill. You are the SCREENWRITER — not the
director, not the VFX reviewer.

### Setup (no user input)

1. Run `./bin/videogen doctor`.
2. If `projects/$1/$2/cast.json` is missing →
   `./bin/videogen cast init --project $1 --episode $2`.
3. Run `./bin/videogen lore show --project $1`. If lore is missing or empty,
   tell the orchestrator — do NOT scaffold lore yourself (the episode
   orchestrator handles that).
4. Run `./bin/videogen cast soul show --project $1 --episode $2` — read
   every soul card.
5. Read `projects/$1/$2/cast.json` to know available characters.

### Write

Draft `projects/$1/$2/script.md` following the screenwriter skill rules:

- 起承转合 narrative arc.
- 画面感优先 — every sentence must be filmable.
- Lift catchphrases, mannerisms, voice_style from soul cards.
- Preserve user-supplied dialog verbatim.
- Honor `lore.forbidden` and each character's `dont` list.
- End with a `<!-- CAST CHECK -->` block listing all characters classified
  as 主角 / 有名NPC / 群演.

### Deliver

Show the full script to the user. Summarize:
- Scene count and approximate pacing.
- Any NPCs identified that need cast generation (from the CAST CHECK).
- Any premise lines you couldn't accommodate and why.

Wait for user approval or edits before the director takes over.
