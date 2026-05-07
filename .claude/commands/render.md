---
description: Render storyboard.json shot-by-shot, then stitch into final mp4.
argument-hint: <project_id> <episode_id>
---

Project: $1, Episode: $2

Activate the `video-director` skill.

1. Confirm storyboard validity:
   `./bin/videogen storyboard validate --project $1 --episode $2`.
2. Run `./bin/videogen storyboard estimate --project $1 --episode $2`.
   Surface the result (shots, total seconds, wall-clock) to the user.
   If the command exits with code 2, STOP and ask for plain-language
   approval before proceeding.
3. Only after explicit user approval, run:
   `./bin/videogen render --project $1 --episode $2 --yes`
   This is sequential and may take 30–90 min. While it runs, monitor
   `projects/$1/$2/shots_state.json` between iterations.
4. If any shot fails, follow the failure-recovery section in the skill.
5. After all shots succeed, run `./bin/videogen stitch --project $1 --episode $2`.
6. Tell the user where the final mp4 is, plus how to re-render any single
   shot with
   `./bin/videogen render --project $1 --episode $2 --shot <id> --force`.
