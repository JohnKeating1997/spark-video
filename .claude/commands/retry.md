---
description: Diagnose a failed shot and re-render it.
argument-hint: <project_id> <episode_id> <shot_id>
---

Project: $1, Episode: $2, Shot: $3

1. Read `projects/$1/$2/shots_state.json` and find shot `$3`. Show the error.
2. Check `projects/$1/$2/storyboard.json` for the shot's prompt + media setup.
3. Apply one of the fixes from the `video-director` skill (prompt rewrite,
   model degrade, content-policy softening, etc.).
4. Update `storyboard.json` if needed.
5. Run `./bin/videogen render --project $1 --episode $2 --shot $3 --force`.
