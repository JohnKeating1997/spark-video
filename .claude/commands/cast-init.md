---
description: Build cast.json for one episode by scanning project + episode cast folders.
argument-hint: <project_id> <episode_id>
---

You are starting (or refreshing) the cast for an episode.

1. Run `./bin/videogen doctor` to verify env.
2. Run `./bin/videogen episode init --project $1 --episode $2` (idempotent;
   makes sure the episode folder skeleton exists).
3. Run `./bin/videogen cast init --project $1 --episode $2`.
   This scans:
     - `projects/$1/cast/<name>/` (project mains, shared across episodes)
     - `projects/$1/$2/cast/<name>/` (episode-only NPCs)
   merges by character name, builds composites *within each character's
   folder*, uploads to OSS, and writes `projects/$1/$2/cast.json`.
4. Read `projects/$1/$2/cast.json` and present the cast as a table
   (image / voice / soul presence / source = project | episode).
5. Run `./bin/videogen cast soul show --project $1 --episode $2` and read
   every soul.
6. For any character missing a soul card, offer to scaffold one with
   `./bin/videogen cast soul template --project $1 [--episode $2] --name <NAME>`
   (use `--episode` only for episode-only NPCs; project mains stay shared).
7. After the user confirms, hand off to `/director $1 $2`.

Activate the `video-director` skill to follow the full pipeline.
