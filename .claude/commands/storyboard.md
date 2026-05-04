---
description: Turn a user's premise into script.md + storyboard.json.
argument-hint: <project_id> "<premise>"
---

Project: $1
Premise: $2

Activate the `video-director` skill.

Steps:
1. Read `projects/$1/cast.json`. If missing, run `/cast-init $1` first.
2. Draft `projects/$1/script.md` based on the premise. Confirm with the user.
3. Compile into `projects/$1/storyboard.json` per the Storyboard schema.
4. Run `videogen storyboard validate --project $1`.
5. Run `videogen storyboard show --project $1` and display to user.
6. Wait for explicit user approval before suggesting `/render $1`.

Target duration: infer from the premise; default 3 minutes (~22 shots).
