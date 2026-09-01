---
name: spark-video-cast
description: Scaffold and generate reference assets for characters (cast), locations (movie-set / set dressing), and key props — the three pillars of visual consistency in spark-video. Uses wan-cli image generation by default. Use when adding new characters/locations/props or when costume/state changes are needed.
---

# Cast / Set / Prop Skill — spark-video Art Department (all-in-one)

You are the **art department** of the pipeline. Your job is to scaffold
folder structures and generate reference images for the three things
that pin visual consistency:

| Pillar | Pins | Folder pattern |
|---|---|---|
| **Cast** | Full-body reference sheet: face, hairstyle, costume, build | `cast/<name>/` |
| **Movie-set** | Locations, lighting, decor | `movie-set/<name>/` |
| **Prop** | Hero objects that recur or change state | `props/<name>/` |

All three follow the **same mental model**: one folder = one reference
image = one frozen visual state. State changes (day→night, intact→torn,
casual→formal) = **separate folders**.

Read `prompt_language` from the project's `lore.md`. Generate cast, set, prop,
and asset-edit prompts in Chinese for `zh`, English for `en`, and the source
description's dominant language for `auto`. Preserve proper names and any
literal text that must appear in the asset. Example commands in this Skill
illustrate structure; their English wording is not a language requirement.

Set env vars:
```bash
export SPARK_VIDEO_PROJECT=<project_id>
export SPARK_VIDEO_EPISODE=<NN>
export SPARK_VIDEO_PHASE=cast-reference
```

## Two-tier model — project vs episode

Both cast, set, and prop live under two tiers. Episode tier overrides
project tier on name collision:

```
projects/<p>/
├── cast/<name>/          ← project mains (shared across all episodes)
├── movie-set/<name>/     ← project recurring locations (sitcom rooms)
├── props/<name>/         ← project recurring hero objects
└── <episode>/
    ├── cast/<name>/      ← episode NPCs OR project-cast overrides (fork)
    ├── movie-set/<name>/ ← one-off locations for this episode
    └── props/<name>/     ← one-off or state-overrides for this episode
```

Use the **project tier** when an asset is shared across episodes
(sitcom recurring rooms, series mains). Use the **episode tier** for
one-off NPCs / locations / state-changes (episode-wide costume forks, episode-only
hero items, one-off rooms).

### Preserve the asset tier

Generate an asset in the same tier as its card. If `cast.md`, `set.md`, or
`prop.md` already exists under the project-global folder, omit `--episode` and
write its reference image there. Use `--episode` only for an intentional
episode-local asset or override, and scaffold/fork that episode asset first so
its folder contains the matching card. Never create an episode folder that has
images but no card; the viewer intentionally displays the two tiers separately.

## ⚠ THE ONE-FOLDER-ONE-STATE RULE (hard rule, applies to all 3)

The video model reads reference images **literally**. Mixing two
visual states into one folder produces a muddy averaged intermediate.

| Pillar | "Same X, different…" → separate folder |
|---|---|
| Cast | Episode-wide costume change (wedding dress / battle wounds / period vs modern) → fork into episode tier |
| Set | Time-of-day (day/night), season (spring/autumn), color grade (cool/warm), weather (clear/rain) |
| Prop | State (intact/creased/torn), damage (clean/bloodied), open/closed |

Naming convention: `<base_name>-<discriminator>`:
- `riverside-inn-lobby-day` / `riverside-inn-lobby-night`
- `red-envelope-intact` / `red-envelope-creased` / `red-envelope-torn`
- `ethan-cole-wedding-attire` (forked from `ethan-cole` for one episode)

## Procedure 1 — scaffold a cast

### Cast reference image contract

Generated cast images should be **character reference sheets**, not
single photoreal portraits. An obviously synthetic character sheet is also
less likely to be mistaken for a real-person headshot.

Make the sheet show the same character in front / side / back views,
with consistent face, hair, costume, build, and a plain background. Default
to no readable text. Watermarks are controlled by the provider and download
policy, not by image-content prompting. Do **not** use provider watermark flags.

### 1.1 Lead / project-tier character

```bash
# Scaffold the folder + soul card template
uv run scripts/scaffold.py cast --name "Ethan Cole"
# Edit projects/<p>/cast/Ethan Cole/cast.md to fill: age, gender, personality, catchphrase,
# visual anchor (one-line appearance), do / don't
```

Then generate the cast reference sheet through the asset wrapper. It invokes
wan-cli and immediately records the returned `taskId`, candidate image URLs,
and downloaded-file hashes in the asset folder. Default to a full-body
standing three-view character sheet rather than a face-only or front-only
portrait. After comparing the candidates, record an Agent default. The default
or later user-selection sidecar makes the manifest and Viewer use the same
primary image; filename ordering is never used as a selection rule:

```bash
uv run scripts/generate_asset.py cast --name "Ethan Cole" \
  --prompt "a three-view drawing of a person, 28-year-old man, short hair, dark T-shirt, full-body character reference sheet, front view, side view, back view, same face and costume in all views, plain background, no readable text" \
  --ratio 16:9 --resolution 2K
```

### Default candidate and optional user override

Every successful `generate_asset.py` call downloads **all** returned
candidates into the asset folder and returns them in `savedFiles`. Preserve
every downloaded candidate. After all independent cast, set, and prop batches
finish, compare each set and record one **default** with `asset-recommend`,
including a short visible-quality rationale in the Agent's working notes. Do
not use filename order as the quality decision and never delete or move the
alternates.

The recorded recommendation is the active default used by manifests and
rendering, so screenwriting and storyboarding may continue without asking the
user to confirm every asset. Rebuild Viewer, point out that defaults can be
changed there, and apply only an actual Viewer handoff or directly stated user
override with `asset-select`. A user override supersedes the Agent default.

```bash
uv run scripts/scaffold.py asset-recommend --kind cast --name "Ethan Cole" \
  --image "Wan_generated_candidate_04.png"
```

```bash
uv run scripts/scaffold.py asset-select --kind cast --name "Ethan Cole" \
  --image "Wan_generated_candidate_04.png"
```

To add an existing local image without changing the current primary image:

```bash
uv run scripts/scaffold.py asset-import --kind cast --name "Ethan Cole" \
  --image "/path/to/new-reference.png"
```

Use `--select` to import and select in one operation. Replace `cast` with
`set` or `prop` for scene and prop assets, and add `--episode` for an
episode-local override. After importing or selecting, rebuild Viewer with
`uv run scripts/build_viewer.py --no-open`.

Viewer can prepare optional asset changes without pretending that a static HTML
page has written to the project. Open a primary or candidate image, use
up/down to move between assets of the same kind and left/right to move between
their candidates, then click **Select + copy for Agent**. Paste that handoff
into the Agent chat; the Agent must run `asset-select`, rebuild the relevant
manifest, and rebuild Viewer before the override is authoritative for rendering.
No handoff means the displayed default remains active.

When the user supplies an original portrait, pass it as `--source-image`. In
the request, describe only pose, composition, background, lighting, and output
format; do **not** restate identity, hair, costume, accessories, body type, or
age. Restating appearance creates a second, fallible source of truth and can
override the actual image. The wrapper locks source appearance at the end of
the compiled prompt and copies the input below `cast/<name>/source/`; that folder is
provenance only and is intentionally excluded from `cast.json`. The generated
candidate recorded by `asset-select` is the reference consumed by storyboards
and video renders:

The project's `initialPrompt.md` or episode `premise.md` must keep the same
input in its ordered `User-provided references` manifest: original attachment
path, stable `source/` copy, and user-stated role. Premise preserves what the
user supplied; `source/` preserves the actual bytes used for reference
generation. Include a Markdown preview such as
`![Image 1](<cast/<name>/source/source-01.png>)` so Viewer displays the original
reference directly. Neither is a substitute for the selected `portrait*.png`.

```bash
uv run scripts/generate_asset.py cast --name "Ethan Cole" \
  --source-image "/path/to/user-reference.png" \
  --prompt "generate a full-body three-view character reference sheet, front, side, back, plain background, no readable text" \
  --ratio 16:9 --resolution 2K
```

If the user explicitly requests a source-image appearance change, add
`--allow-source-appearance-change` and name only the requested change. Without
that flag, conflicting appearance text is deliberately subordinated to the
source image.

Before generation, visually inspect the actual local source file. If the card's
`visual_anchor` conflicts with it, stop and correct the card from visible facts;
never overwrite the source-derived appearance with an unsupported description.
After generation, record an Agent default before running `cast-init`; a later
`scaffold.py asset-select` records the user's override. Legacy `portrait*.png`
selection is still accepted when neither sidecar exists. When `source/` exists,
`cast-init` publishes only the default or selected generated image and excludes
both source inputs and unselected Wan candidates.

Notes:
- **Reference tags follow the Wan site, not creative prompt language**: CN uses
  `@图片1`, `@图片2`, ...; international uses `@Image1`, `@Image2`, .... The
  wrapper inserts them in uploaded-image order.
- **Default wan-cli image model**: use the installed CLI default so asset
  generation stays aligned with the same Wan account and authentication.
  Do not force `wan3.0`: the current CLI exposes Wan 3.0 for Omni video, while
  `image2image` supports the 2.x image model line (`2_7`, `2_7_flash`, `2_6`,
  `2_5`).
- **Do not append `lore.mood_anchor` manually.** The asset prompt compiler
  injects only art-direction fields compatible with `lore.visual_medium`.
  Source-image identity, hair, costume, accessories, body type, and apparent
  age remain authoritative.
- **Keep `mood_anchor` global.** It may contain only lighting, palette,
  contrast, texture, and atmosphere shared by every asset and shot. Never put
  a named character's face, hair, costume, accessories, body type, or age in
  it; keep those in that character's cast card. Put recurring compositional
  emphasis in `imagery_system.highlight_elements`.
- **Mixed projects still generate concrete assets.** Pass `--visual-medium`
  for each cast/set/prop asset in a mixed project. Do not ask one reference
  sheet to average multiple media.
- **Prefer generated / hand-drawn character sheets over real-person
  photos** for providers with input privacy checks. If you drop a real
  actor reference into the folder, make sure you have the right to use it
  and that your target provider accepts real-person inputs; it overrides
  the generated reference sheet at r2v time.

Optional: voice reference for reference-voice r2v (Wan / bl both support):
- Drop a 5–10s clean speech sample as `voice.mp3` in the cast folder.

### 1.2 NPC (episode-only)

```bash
uv run scripts/scaffold.py cast --name "Madam Quinn" --episode
# → projects/<p>/<ep>/cast/Madam Quinn/

uv run scripts/generate_asset.py cast --name "Madam Quinn" --episode \
  --prompt "a three-view drawing of a person, middle-aged woman, stout build, dark silk hanfu, gold hairpin, shrewd worldly expression, full-body character reference sheet, front view, side view, back view, same face and costume in all views, plain background, no readable text" \
  --ratio 16:9 --resolution 2K
```

Then re-init the merged cast.json:
```bash
uv run scripts/scaffold.py cast-init   # merges project + episode tiers
```

### 1.3 Cast fork — episode-wide costume change

When a character needs a different outfit for THIS episode only (wedding,
period costume, battle-damaged version), DO NOT solve it in shot prompts. Fork the cast reference:

```bash
# Deep-copy the project cast folder into the episode, drop old reference images
uv run scripts/scaffold.py cast --fork --name "Ethan Cole" --drop-portraits

# Regenerate the reference sheet with the new appearance
uv run scripts/generate_asset.py cast --name "Ethan Cole" --episode \
  --image "projects/$SPARK_VIDEO_PROJECT/cast/Ethan Cole/portrait1.png" \
  --prompt "Create a three-view drawing of the same person. Change the character's outfit to a large red traditional Chinese wedding robe and red wedding cap; keep face and hairstyle unchanged. Output a full-body character reference sheet with front view, side view, back view, same face and costume in all views, plain background, no readable text" \
  --generation-mode reference

uv run scripts/scaffold.py cast-init
```

`wan image2image --generation-mode reference` preserves face identity better
than text-to-image for forks — prefer it when a project-tier reference exists.

For pixel-perfect face identity (edit can still drift slightly), drop
a hand-edited PNG / three-view sheet into the episode cast folder instead
of regenerating it.

## Procedure 2 — scaffold a movie-set

### 2.1 When to scaffold a set

Scaffold whenever:
- Two or more shots happen in the same location with the same lighting.
- The location matters enough that drift would be noticeable (recurring
  sitcom rooms, hero locations, key emotional spaces).
- A location returns under DIFFERENT lighting → scaffold one new folder
  per lighting state.

Skip for one-shot pass-throughs or pure outdoors with no fixed landmarks.

### 2.2 Naming — lighting state in the folder name

| Same physical place, different… | Action |
|---------------------------------|--------|
| Time-of-day (day / dusk / night / pre-dawn) | **Separate folders** (`inn-lobby-day`, `inn-lobby-night`) |
| Season (spring / summer / autumn / winter) | Separate if visible (willows / snow / red leaves) |
| Color grade (memory cold gray / present warm yellow / high-contrast neon) | Separate folders |
| Weather (clear / rain / snow / fog) | Separate when weather is in frame |
| Decor unchanged, action just moves around the room | **Same folder** |

### 2.3 Scaffold + generate

```bash
# Project-tier sitcom recurring room
uv run scripts/scaffold.py set --name "riverside-inn-lobby-day"

# Episode-tier one-off
uv run scripts/scaffold.py set --name "rental-apartment-living-room-warm-light" --episode

# Generate the reference image (description MUST include the lighting/
# season/tone you committed to in the folder name)
uv run scripts/generate_asset.py set --name "riverside-inn-lobby-day" \
  --prompt "Ming-Qing style wooden inn lobby, two-story wooden staircase, red lanterns, three square tables, daytime natural light through windows, warm yellow tone" \
  --ratio 16:9 --resolution 2K

# Rebuild movie_set.json
uv run scripts/scaffold.py set-init
```

The `set.md` frontmatter has explicit `time_of_day` / `season` /
`color_grade` / `lighting` / `weather` axes — fill them in. They're
informational today, but they're the contract that prevents a future
director from reusing a daytime set in a night shot.

## Procedure 3 — scaffold a prop

### 3.1 When to promote an object to a key prop

Promote any object to a key prop when it satisfies **either**:
- It appears in 2+ shots and the audience would notice if it changed
  shape/material/color/wear (the red envelope in S01-003 → S01-007 → S04-002).
- It's a story-critical hero object even in a single shot (the ring
  proposal close-up; the key reveal).

Skip for background dressing or non-recurring objects whose look doesn't
matter to the plot. **Budget: 3–6 named props per episode**, more is a smell.

### 3.2 Scaffold + generate

```bash
# Project-tier recurring prop (family heirloom)
uv run scripts/scaffold.py prop --name "heirloom-ring-intact"

# Episode-tier one-off or state-change
uv run scripts/scaffold.py prop --name "red-envelope-creased" --episode

# Generate a clean product-style reference image when no photo exists
uv run scripts/generate_asset.py prop --name "red-envelope-intact" \
  --prompt "Red gift envelope, large gold-stamped wedding emblem, flat with no creases, pure white background, product photography style" \
  --ratio 1:1 --resolution 2K

# State change — produce creased state as a separate folder + image
uv run scripts/generate_asset.py prop --name "red-envelope-creased" --episode \
  --image projects/$SPARK_VIDEO_PROJECT/props/red-envelope-intact/prop1.png \
  --prompt "Add obvious creases and grip-worn folds to the red envelope; keep color, print, and shape exactly unchanged" \
  --generation-mode reference

# Rebuild props.json
uv run scripts/scaffold.py prop-init
```

For state changes, **always prefer `wan image2image --generation-mode reference`**
with the base state image. Text-to-image from scratch will drift.

## Generation tips (apply to all three)

### Mood anchor — append it to every t2i prompt

```bash
# Helper that prints lore's mood_anchor for piping:
uv run scripts/scaffold.py mood-anchor
```

Without it, your asset visual style won't match the rendered shots.

### Aspect ratio defaults

| Asset type | `--ratio` |
|---|---|
| Cast reference sheet (full-body three-view, default) | `16:9` |
| Legacy single cast portrait (only when provider accepts it) | `3:4` or `9:16` |
| Set establishing | `16:9` |
| Prop (product-style) | `1:1` |

### Batch generation in parallel

Run independent asset-wrapper tasks in parallel when scaffolding many NPCs or
sets. Download and preserve every candidate, record one Agent default per asset,
then present all batches together in Viewer as an optional review surface.

```bash
uv run scripts/generate_asset.py cast --name "Ethan Cole" --prompt "..."
```

### Multi-image merge (cast fork only)

The wrapper accepts repeated `--image` arguments for multi-reference work.
This is useful when forking a cast with a costume reference photo:

```bash
uv run scripts/generate_asset.py cast --name "Ethan Cole" --episode \
  --image "cast/Ethan Cole/portrait1.png" \
  --image refs/hanfu-reference.png \
  --prompt "Dress the person in Image 1 in the traditional outfit from Image 2; keep face and hairstyle unchanged" \
  --generation-mode reference
```

Each successful generation appends an exact record to
`.wan-generations.jsonl` in that asset folder. Manifest rebuilds match files by
SHA-256 (not filename or history search), so renaming a selected candidate keeps
its original `taskId` and `image_url`. The sidecar also stores the returned
`image_urls` list directly. Do not delete this sidecar.

## After scaffolding — rebuild manifests

The merged manifests (`cast.json`, `movie_set.json`, `props.json`)
must be rebuilt after any folder change. They drive the director's
shot-id lookups and the renderer's media[] resolution:

```bash
uv run scripts/scaffold.py cast-init
uv run scripts/scaffold.py set-init
uv run scripts/scaffold.py prop-init
# or all three:
uv run scripts/scaffold.py manifests
```

Tell the director (or the producer at GATE 2) when you've added new
assets — they need to read the updated manifests before storyboarding
any scene that references them.

## DON'Ts

- ❌ Don't use candidate 1 merely because of filename order. Compare the
  candidates and record a reasoned Agent default; preserve the user's ability
  to override it later in Viewer.
- ❌ Don't delete unselected candidates. Viewer keeps them for comparison,
  later changes, and provenance.
- ❌ Don't put two lighting states (day + night) in the same set folder.
  The model averages and produces "neutral gray noon-night" garbage.
- ❌ Don't put two prop states (intact + creased) in the same prop folder.
  Same reason.
- ❌ Don't solve a costume change by writing "wearing XXX" in shot prompts.
  Fork the cast reference sheet instead.
- ❌ Don't omit the mood_anchor in t2i prompts. Visual cohesion will
  break across shots vs cast references.
- ❌ Don't use generic names like `cast/nurse` — name by role+story-id
  (`cast/nurse-xiaoli`). When two episodes both have a "nurse", you can't tell
  whose cast reference is whose.
- ❌ Don't use provider / CLI watermark flags such as `--watermark` or
  request a watermark as image content. Keep `no readable text` as a content
  constraint; watermark handling belongs to provider and download policy.
- ❌ Don't skip `scaffold.py *-init` after adding folders. The manifests
  are the only thing the rest of the pipeline reads.
