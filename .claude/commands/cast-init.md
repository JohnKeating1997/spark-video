---
description: Scan ./cast/, upload portraits + voices to OSS, write cast.json.
argument-hint: <project_id> [cast_dir]
---

You are starting a new long-form video project.

1. Run `videogen doctor` to verify env.
2. Run `videogen cast init --project $1 ${2:+--dir $2}`.
3. Read `projects/$1/cast.json` and present the cast as a table.
4. Ask the user to confirm the cast list before continuing to the script.

Activate the `video-director` skill to follow the full pipeline.
