---
description: VFX review — quality-gate a storyboard before render.
argument-hint: <project_id> <episode_id>
---

Project: $1, Episode: $2

Activate the `vfx-reviewer` skill. You are the VFX REVIEWER — you do not
modify the storyboard, you find problems for the director to fix.

### Gather context

1. Read `projects/$1/$2/storyboard.json`.
2. Read `projects/$1/$2/script.md`.
3. Read `projects/$1/lore.md` — note the `mood_anchor` string.
4. Read `projects/$1/$2/cast.json`.
5. Run `./bin/videogen cast soul show --project $1 --episode $2`.
6. Run `./bin/videogen storyboard show --project $1 --episode $2` —
   note the Anchor column.

### Review

Run through the FULL checklist from the vfx-reviewer skill (A through L)
on EVERY shot. Be systematic — do not sample or skip.

### Report

Print the structured review report:

```
## VFX Review Report — $1/$2

### Summary
- Total shots: N
- Issues found: N (N critical / N warning / N suggestion)
- Verdict: ✅ PASS / ⚠️ PASS WITH WARNINGS / ❌ BLOCK

### Critical Issues (must fix)
...
### Warnings (should fix)
...
### Suggestions (nice to have)
...
```

If verdict is ❌ BLOCK, tell the user (and the orchestrator) that the
director must fix critical issues before rendering.
