---
description: Render storyboard.json shot-by-shot, then stitch into final mp4.
argument-hint: <project_id>
---

Project: $1

Activate the `video-director` skill.

1. Confirm storyboard validity: `./bin/videogen storyboard validate --project $1`.
2. Estimate wall-clock & cost; ask the user to confirm before kicking off.
3. Run `./bin/videogen render --project $1` — this is sequential and may take 30–90 min.
   While it runs, monitor `projects/$1/shots_state.json` between iterations.
4. If any shot fails, follow the failure-recovery section in the skill.
5. After all shots succeed, run `./bin/videogen stitch --project $1`.
6. Tell the user where the final mp4 is, plus how to re-render any single shot
   with `./bin/videogen render --project $1 --shot <id> --force`.
