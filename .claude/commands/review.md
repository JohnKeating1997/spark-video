---
description: Run the per-clip video reviewer on already-rendered shots. Use when you want to score clips without (re)rendering, or to debug a low-scoring shot in detail.
argument-hint: <project_id> <episode_id> [<shot_id>]
---

Project: $1
Episode: $2
Shot (optional): $3

You are the **video-reviewer**. Read the `video-reviewer` skill at
`.claude/skills/video-reviewer/SKILL.md` first, then act per its rules.

## Phase 0 — pick targets

If `$3` is set, you score that shot only. Otherwise, score every shot
that has at least one SUCCEEDED attempt and `winner_version == null` OR
the user is asking for a full re-pass.

Snapshot the current state:

```bash
./bin/videogen storyboard show --project $1 --episode $2
```

## Phase 1 — review

For each target shot:

```bash
./bin/videogen review --project $1 --episode $2 --shot <SHOT> [--ver <N>]
```

The CLI calls qwen3-vl-plus and prints a JSON `{score, breakdown, critique, verdict}`.
The same JSON is written to `projects/$1/$2/reviews/<SHOT>-ver<N>.json`.

## Phase 2 — report

Show the user a compact table:

```
shot       ver  score  logic prop physics style  verdict
S01-001    1    8.2    8     8    8       9      ACCEPT
S01-002    1    6.5    7     5    6       8      REJECT
...
```

For every REJECT, show the `critique` indented underneath.

## Phase 3 — what next

- If everything is ACCEPT → done.
- If any REJECT and the shot has not been re-rendered yet → suggest:
  ```
  ./bin/videogen render --project $1 --episode $2 --shot <SHOT> --force
  ```
  (the render loop re-reviews + auto-rewrites + escalates as needed.)
- If a shot was already through 3 attempts → escalate to the director
  per the SKILL's "Escalation" section. Write
  `projects/$1/$2/reviews/escalation-<SHOT>.md` and tell the user to
  hand it to the director skill.
