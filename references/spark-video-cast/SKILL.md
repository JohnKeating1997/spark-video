---
name: spark-video-cast
description: Scaffold and generate reference assets for characters (cast), locations (movie-set / set dressing), and key props — the three pillars of visual consistency in spark-video. Wraps bl image generate / edit for cast reference sheet creation. Use when adding new characters/locations/props or when costume/state changes are needed.
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

## ⚠ THE ONE-FOLDER-ONE-STATE RULE (hard rule, applies to all 3)

The video model reads reference images **literally**. Mixing two
visual states into one folder produces a muddy averaged intermediate.

| Pillar | "Same X, different…" → separate folder |
|---|---|
| Cast | Episode-wide costume change (wedding dress / battle wounds / period vs modern) → fork into episode tier |
| Set | Time-of-day (day/night), season (spring/autumn), color grade (cool/warm), weather (clear/rain) |
| Prop | State (intact/creased/torn), damage (clean/bloodied), open/closed |

Naming convention: `<base_name>-<discriminator>`:
- `同福客栈大堂-白天` / `同福客栈大堂-夜晚`
- `红包-完整` / `红包-起皱` / `红包-撕碎`
- `陆辰-汉服` (forked from `陆辰` for one episode)

## Procedure 1 — scaffold a cast

### Cast reference image contract

Generated cast images should be **character reference sheets**, not
single photoreal portraits. Seedance-style providers are less likely to
reject an obviously synthetic character sheet than a realistic headshot.

Every cast-image generation prompt MUST include this intent:

> a three-view drawing of a person and annotate it with an AI-generated, non-real-person watermark on the bottom

Make the sheet show the same character in front / side / back views,
with consistent face, hair, costume, build, and a plain background. The
bottom annotation is part of the image content for safety provenance;
do **not** use provider watermark flags. Avoid any other readable text.

### 1.1 Lead / project-tier character

```bash
# Scaffold the folder + soul card template
uv run scripts/scaffold.py cast --name "陆辰"
# Edit projects/<p>/cast/陆辰/cast.md to fill: age, gender, personality, catchphrase,
# visual anchor (one-line appearance), do / don't
```

Then generate the cast reference sheet via bl. Default to a full-body
standing character sheet / 三视图 rather than a face-only or front-only
portrait. Keep the `portrait` filename prefix for compatibility with the
rest of the pipeline:

```bash
./scripts/bl image generate \
  --model wan2.6-t2i \
  --prompt "a three-view drawing of a person and annotate it with an AI-generated, non-real-person watermark on the bottom, 28-year-old man, short hair, dark T-shirt, full-body character reference sheet, front view, side view, back view, same face and costume in all views, plain background, no other readable text, $(uv run scripts/scaffold.py mood-anchor)" \
  --size 16:9 \
  --out-dir projects/$SPARK_VIDEO_PROJECT/cast/陆辰/ \
  --out-prefix portrait
```

Notes:
- **Default model `wan2.6-t2i`**: produces stable cast reference sheets
  compatible with downstream r2v. `qwen-image-2.0` is newer but visual
  style differs; test before switching.
- **Append `lore.mood_anchor`** to every cast-reference prompt so the visual
  style matches the rest of the production. The `scaffold.py mood-anchor`
  helper prints lore's mood_anchor for piping.
- **Prefer generated / hand-drawn character sheets over real-person
  photos** for providers with input privacy checks. If you drop a real
  actor reference into the folder, make sure you have the right to use it
  and that your target provider accepts real-person inputs; it overrides
  the generated reference sheet at r2v time.

Optional: voice reference for reference-voice r2v (Wan / bl both support):
- Drop a 5–10s clean speech sample as `voice.mp3` in the cast folder.

### 1.2 NPC (episode-only)

```bash
uv run scripts/scaffold.py cast --name "钱夫人" --episode
# → projects/<p>/<ep>/cast/钱夫人/

./scripts/bl image generate \
  --model wan2.6-t2i \
  --prompt "a three-view drawing of a person and annotate it with an AI-generated, non-real-person watermark on the bottom, middle-aged woman, stout build, dark silk hanfu, gold hairpin, shrewd worldly expression, full-body character reference sheet, front view, side view, back view, same face and costume in all views, plain background, no other readable text, $(uv run scripts/scaffold.py mood-anchor)" \
  --size 16:9 \
  --out-dir projects/$SPARK_VIDEO_PROJECT/episode-$SPARK_VIDEO_EPISODE/cast/钱夫人/ \
  --out-prefix portrait
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
uv run scripts/scaffold.py cast --fork --name "陆辰" --drop-portraits

# Regenerate the reference sheet with the new appearance
./scripts/bl image edit \
  --image projects/$SPARK_VIDEO_PROJECT/cast/陆辰/portrait1.png \
  --prompt "Create a three-view drawing of the same person and annotate it with an AI-generated, non-real-person watermark on the bottom. Change the character's outfit to a large red traditional Chinese wedding robe and red wedding cap; keep face and hairstyle unchanged. Output a full-body character reference sheet with front view, side view, back view, same face and costume in all views, plain background, no other readable text, $(uv run scripts/scaffold.py mood-anchor)" \
  --out-dir projects/$SPARK_VIDEO_PROJECT/episode-$SPARK_VIDEO_EPISODE/cast/陆辰/ \
  --out-prefix portrait

uv run scripts/scaffold.py cast-init
```

`bl image edit` preserves face identity better than `bl image generate`
for forks — always prefer edit when you have a project-tier reference sheet
or portrait to base from.

For pixel-perfect face identity (edit can still drift slightly), drop
a hand-edited PNG / three-view sheet into the episode cast folder instead
of using bl.

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
| Time-of-day (day / dusk / night / pre-dawn) | **Separate folders** (`客栈大堂-白天`, `客栈大堂-夜晚`) |
| Season (spring / summer / autumn / winter) | Separate if visible (willows / snow / red leaves) |
| Color grade (memory cold gray / present warm yellow / high-contrast neon) | Separate folders |
| Weather (clear / rain / snow / fog) | Separate when weather is in frame |
| Decor unchanged, action just moves around the room | **Same folder** |

### 2.3 Scaffold + generate

```bash
# Project-tier sitcom recurring room
uv run scripts/scaffold.py set --name "同福客栈大堂-白天"

# Episode-tier one-off
uv run scripts/scaffold.py set --name "出租屋客厅-暖灯" --episode

# Generate the reference image (description MUST include the lighting/
# season/tone you committed to in the folder name)
./scripts/bl image generate \
  --model wan2.6-t2i \
  --prompt "Ming-Qing style wooden inn lobby, two-story wooden staircase, red lanterns, three square tables, daytime natural light through windows, warm yellow tone, $(uv run scripts/scaffold.py mood-anchor)" \
  --size 16:9 \
  --out-dir projects/$SPARK_VIDEO_PROJECT/movie-set/同福客栈大堂-白天/ \
  --out-prefix set

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
uv run scripts/scaffold.py prop --name "戒指-完整"

# Episode-tier one-off or state-change
uv run scripts/scaffold.py prop --name "红包-起皱" --episode

# Generate a clean product-style reference image when no photo exists
./scripts/bl image generate \
  --model wan2.6-t2i \
  --prompt "Standard Chinese red envelope, large red hot-stamped pattern, printed with '囍', flat with no creases, pure white background, product photography style, $(uv run scripts/scaffold.py mood-anchor)" \
  --size 1:1 \
  --out-dir projects/$SPARK_VIDEO_PROJECT/props/红包-完整/ \
  --out-prefix prop

# State change — produce creased state as a separate folder + image
./scripts/bl image edit \
  --image projects/$SPARK_VIDEO_PROJECT/props/红包-完整/prop1.png \
  --prompt "Add obvious creases and grip-worn folds to the red envelope; keep color, print, and shape exactly unchanged" \
  --out-dir projects/$SPARK_VIDEO_PROJECT/episode-$SPARK_VIDEO_EPISODE/props/红包-起皱/ \
  --out-prefix prop

# Rebuild props.json
uv run scripts/scaffold.py prop-init
```

For state changes, **always prefer `bl image edit`** with the base state
image as input — preserves shape/print/material continuity. `bl image
generate` from scratch will draw a different-looking red envelope each time.

## Generation tips (apply to all three)

### Mood anchor — append it to every t2i prompt

```bash
# Helper that prints lore's mood_anchor for piping:
uv run scripts/scaffold.py mood-anchor
```

Without it, your asset visual style won't match the rendered shots.

### Aspect ratio defaults

| Asset type | `--size` |
|---|---|
| Cast reference sheet (full-body three-view, default) | `16:9` |
| Legacy single cast portrait (only when provider accepts it) | `3:4` or `9:16` |
| Set establishing | `16:9` |
| Prop (product-style) | `1:1` |

### Batch generation in parallel

`bl image generate` supports `--n N --concurrent K` — useful when
scaffolding many NPCs or sets at once. Each `--n` produces a candidate;
keep the best, delete the rest.

```bash
./scripts/bl image generate --n 3 --concurrent 3 \
  --model wan2.6-t2i \
  --prompt "..." \
  --out-dir projects/.../cast/陆辰/ \
  --out-prefix candidate
# → candidate1.png, candidate2.png, candidate3.png; rename winner to portrait1.png
```

### Multi-image merge (cast fork only)

`bl image edit` accepts multiple `--image` flags. Useful when forking a
cast with a costume reference photo:

```bash
./scripts/bl image edit \
  --image cast/陆辰/portrait1.png \
  --image refs/hanfu-reference.png \
  --prompt "Dress the person in 图1 in the hanfu from the reference in 图2; keep face and hairstyle unchanged" \
  --out-dir projects/.../episode-X/cast/陆辰/
```

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
- ❌ Don't use provider / CLI watermark flags such as `--watermark`.
  For generated **cast** sheets, ask for the bottom provenance
  annotation in the prompt itself:
  `AI-generated, non-real-person`. Keep it outside the character body
  and avoid any other readable text.
- ❌ Don't skip `scaffold.py *-init` after adding folders. The manifests
  are the only thing the rest of the pipeline reads.
