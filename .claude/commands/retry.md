---
description: Diagnose a failed shot and re-render it.
argument-hint: <project_id> <shot_id>
---

Project: $1, Shot: $2

1. Read `projects/$1/shots_state.json` and find shot `$2`. Show the error.
2. Check `projects/$1/storyboard.json` for the shot's prompt + media setup.
3. Apply one of the fixes from the `video-director` skill (prompt rewrite,
   model degrade, content-policy softening, etc.).
4. Update `storyboard.json` if needed.
5. Run `videogen render --project $1 --shot $2 --force`.
