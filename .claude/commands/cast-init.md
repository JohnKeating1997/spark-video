---
description: Scan ./cast/, upload portraits + voices to OSS, write cast.json.
argument-hint: <project_id> [cast_dir]
---

You are starting a new long-form video project.

1. Run `./bin/videogen doctor` to verify env.
2. Run `./bin/videogen cast init --project $1 ${2:+--dir $2}`.
3. Read `projects/$1/cast.json` and present the cast as a table (image / voice / soul presence).
4. Run `./bin/videogen cast soul show --project $1` and read every soul.
5. For any character missing a soul card, offer to scaffold one with
   `./bin/videogen cast soul template --name <NAME>` and walk the user through
   filling in archetype / voice / catchphrase / one key relationship.
6. After the user confirms, hand off to `/storyboard $1 "<premise>"`.

Activate the `video-director` skill to follow the full pipeline.
