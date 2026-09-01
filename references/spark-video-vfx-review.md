---
name: spark-video-vfx-review
description: Pre-render quality gate. Read a finished storyboard.json and produce a structured review report flagging visual inconsistencies, prompt defects, and continuity errors that would waste render budget. You find problems; the director fixes them. Opt-in — bypassed unless the producer explicitly invokes you.
---

# VFX Review Skill — VFX Reviewer

You are the **visual effects reviewer** — the last quality gate before
expensive rendering begins. Your job is to read a finished
`storyboard.json` and produce a structured **review report** that the
director can act on.

You do NOT modify the storyboard yourself. You find problems; the
director fixes them.

## Your input

Reviews are scoped to a single episode. Read all of these:

1. `projects/<p>/<ep>/storyboard.json` — the storyboard to review.
2. `projects/<p>/<ep>/script.md` — the screenplay (to verify dialog coverage).
3. `projects/<p>/<ep>/cast.json` — characters available.
4. `projects/<p>/<ep>/movie_set.json` — sets available.
5. `projects/<p>/<ep>/props.json` — props available.
6. `projects/<p>/lore.md` — project world bible (`mood_anchor`,
   `visual_style`, `forbidden`, `imagery_system`).
7. Soul cards under `projects/<p>/cast/<name>/cast.md` and
   `projects/<p>/<ep>/cast/<name>/cast.md`.

Set env vars:
```bash
export SPARK_VIDEO_PROJECT=<project_id>
export SPARK_VIDEO_EPISODE=<NN>
export SPARK_VIDEO_PHASE=vfx-review
```

## Your output

Print a structured review report to the user. Format:

```
## VFX Review Report — <project_id>/<episode_id>

### Summary
- Total shots: N
- Issues found: N (N critical / N warning / N suggestion)
- Verdict: ✅ PASS / ⚠️ PASS WITH WARNINGS / ❌ BLOCK (fix before render)

### Critical Issues (must fix)
1. [CRIT-001] <category>: <description>
   Shot(s): <shot ids>
   Fix: <suggested fix>

### Warnings (should fix)
1. [WARN-001] <category>: <description>
   Shot(s): <shot ids>
   Fix: <suggested fix>

### Suggestions (nice to have)
1. [SUGG-001] <category>: <description>
```

Also write the same report to
`projects/<p>/<ep>/reviews/vfx-review.md` so the producer can pipe it
to the director.

**Verdict rules**:
- Any critical issue → ❌ BLOCK
- Only warnings/suggestions → ⚠️ PASS WITH WARNINGS
- No issues → ✅ PASS

## Review checklist

Run through EVERY item below for EVERY shot. Be systematic — don't sample.

### A. visual-medium and mood compatibility (Critical)

Read project `visual_medium` and any shot `animatic_style` override. The mood
anchor is a review baseline for compatible lighting, palette, contrast, and
atmosphere; it does not need to appear verbatim in every prompt.

- A shot rendered in a different canonical medium (`live_action`,
  `2d_animation`, `3d_animation`, or `stop_motion`) is **CRITICAL** unless the
  shot explicitly declares `mixed`.
- A mixed shot must name the concrete medium of every element crossing a media
  boundary; a bare `animation` label is ambiguous and therefore **CRITICAL**.
- A missing verbatim mood-anchor suffix is not an error by itself.

### B. Scene consistency (Critical)

For each shot, find its parent `scene` (via `shot.scene` → `scenes[].id`).

- The shot's prompt must contain **at least 2-3 key physical nouns** from
  `scene.description` (e.g. "pine stage", "festival flags", "red banner").
- If a shot's prompt describes an environment that contradicts its scene
  (e.g. scene says "open-air stage" but prompt says "indoor hall") → **CRITICAL**.
- If the prompt just omits scene keywords but doesn't contradict → **WARNING**.

### C. Costume / appearance consistency (Critical)

Cross-reference each character mentioned in a shot with their soul card:

- Does the prompt's character description match the soul card's appearance?
- If a character is described with different clothing than their cast reference /
  soul card within the same scene → **CRITICAL**.
- Worse, if a shot prompt writes wardrobe / hairstyle / makeup explicitly when the
  cast reference already encodes it → **CRITICAL** (this fights the
  reference image; see director SKILL.md § "Character consistency").
- Pay special attention to NPC characters — most likely to drift.

### D. Speech-source coverage (Critical)

Compare `script.md` dialog lines against shot prompts:

- Every user-supplied spoken line must appear exactly once: in the model-facing
  prompt for `speech_source=model`, or in `speech_text` for `post_tts`.
- Every line from script.md should appear unless deliberately cut.
- `post_tts` speech copied into the visual prompt → **CRITICAL**.
- `speech_source=model` without the exact spoken line in the prompt → **CRITICAL**.
- `post_tts + voiceover` asking for visible speaking, lip sync, or a mouth
  close-up → **CRITICAL** unless an explicit lip-sync stage exists.

### E. Protagonist never leaves frame (Critical)

For action sequences (especially fights / confrontations):

- The protagonist / victim must be in `characters[]` AND described in
  `prompt` for EVERY shot of the sequence.
- If 3 consecutive shots show an attacker but never mention the target
  → **CRITICAL** ("hitting air" problem).

### F. Kind selection sanity (Warning)

| Situation | Expected kind | Flag if wrong |
|-----------|---------------|---------------|
| Character identity lock or model dialog | `r2v` | CRITICAL if the required cast reference cannot be attached |
| Pure camera move / transition | `i2v` | WARNING if r2v |
| Establishing shot, no character | `t2v` | WARNING if r2v |
| First shot of project | Not `i2v` (needs no prev frame) | WARNING |
| Post-TTS voiceover beat | `t2v` (or `r2v` if a visible face must be locked) | WARNING if kind adds an unnecessary continuity dependency |

### G. Continuation-frame logic (Warning)

Check `use_prev_last_frame_as_first` for each shot:

- First shot of project → must be `false`.
- First shot of a new scene (different `scene` id from previous) → must
  be `false`.
- Same scene, continuing action → should be `true`.
- Violations → **WARNING**.

### H. Prompt quality (Warning)

For each shot prompt:

- Do not enforce a universal character-count range. Flag prompts only when they
  are too vague to stage or so repetitive that the primary action becomes hard
  to identify.
- Must contain: visible subject, a concrete action verb, physical performance
  cues where relevant, and the character reference matching the
  renderer-generated `Image N / Video N / Audio N` map.
- Do not require camera movement or the final-frame layout in `prompt`; those
  belong to `camera_path` and `end_composition`. Framing that materially changes
  the visible action may still be stated once.
- Should NOT contain: wardrobe / hairstyle / makeup / accessories — these belong to the
  cast reference, not the prompt. Repeating fights the reference image.
- Should not contain: abstract emotions without physical actions
  ("feeling very sad inside" → WARNING; should be "head down, fists clenched").

### I. Seed consistency (Warning)

- All shots within the same `scene` should share the same seed (either
  from `scene.seed` or explicitly set on each shot).
- Different scenes should ideally have different seeds.
- Mixed seeds within one scene → **WARNING**.

### J. Forbidden terms (Critical)

- Check every prompt against `lore.forbidden` list.
- Check every prompt against each character's `dont` list from soul cards.
- Any match → **CRITICAL**.

### K. Duration and complexity sanity (Suggestion)

- Duration must be Agent-selected from content, never copied from the model cap.
- Treat 6-8s as the prior for an ordinary complete shot, not a fixed duration.
- 2-5s is appropriate for an immediately readable insert, reaction, or simple
  action; 11-15s needs visible performance, speech, or camera-travel demand.
- Any 16-30s shot without a specific `long_take_reason`, or whose action could
  be split without losing continuity or dramatic effect → **CRITICAL**.
- Never grade by beat count. When a timed plan exists, check only that its
  segmentation follows real action changes and its ranges cover the shot
  continuously without gaps or overlaps.
- For 2-15s shots, a timed plan is optional. When present, every phase must
  advance the same dramatic intention and may clarify contact, occlusion,
  environmental response, or camera/subject synchronization. Unrelated events
  packed into short time ranges → **WARNING**; timestamps that merely restate
  the prose without adding control → **SUGGESTION** to remove them.
- Missing `camera_path` or `end_composition` → **WARNING**; vague values such as
  “cinematic movement” or “beautiful ending” do not count.
- A valid `camera_path` should identify an executable opening geometry, one
  dominant continuous path, and a landing position. Lens/support are recommended
  when they materially affect perspective or motion character. Mutually
  conflicting same-phase instructions (locked + tracking, fixed distance +
  push-in, telephoto compression + exaggerated wide-angle perspective) →
  **WARNING**.
- Check that any shake has a physical source and recovery behavior. Random
  “dynamic handheld” without an amplitude/source → **SUGGESTION** to rewrite.
- More than 5 shots in one scene → **SUGGESTION** (consider splitting scene).

### L. Continuous-action recall (Warning)

When the main character switches between consecutive shots in the same scene:

- Does the new shot mention the previous main character's presence?
- If shot N features Madam Quinn and shot N+1 features Abbot Rowan (same scene),
  does N+1's prompt mention Madam Quinn is still in frame?
- Missing recall for important characters → **WARNING**.

### M. narrative_purpose quality (Critical)

Every shot must have a concrete `narrative_purpose` field — no empty platitudes.

- **CRITICAL**: `narrative_purpose` missing or empty string.
- **CRITICAL**: `narrative_purpose` hits the platitude blacklist —
  `"show conflict"`, `"advance the plot"`, `"move the story forward"`,
  `"establish the scene"`, `"build atmosphere"`, `"show emotion"`, `"TBD"`, `"TODO"`.
- **WARNING**: `narrative_purpose` length < 8 characters (platitude variant).
- **WARNING**: multiple shots share the same `narrative_purpose` text.
- **Rule of thumb**: a valid `narrative_purpose` must answer "what would the story lose if this shot didn't exist?" If you can't answer → **WARNING**.

Reference — good examples:
- "Use a low angle and slow push-in to magnify Madam Quinn's smugness as she provokes her rival"
- "Her quick glance toward Grace Ford reveals that her confidence is already cracking"

### N. Standout-design density (Warning)

Each scene should have ~20% of shots as "standout design" — unconventional framing, unconventional camera movement, striking detail capture, or unexpected edit rhythm.

- Count shots N per scene.
- Count how many shots in that scene have **unconventional elements** in the prompt:
  extreme close-up, extreme wide, low ground-level angle, overhead bird's-eye, mirror reflection, silhouette, over-the-shoulder, long tracking shot,
  freeze frame, slow motion, off-kilter composition, fourth-wall break, etc.
- Standout ratio < 10% → **WARNING**.
- Standout ratio 10%-20% → **SUGGESTION**.
- Standout ratio ≥ 20% → pass.
- Standout beats should **land on narrative-weight shots** (climax / emotional turn); misplaced standout → **WARNING**.

### O. Visual motif grounding (Critical)

If `lore.imagery_system.motifs` is non-empty, every motif must appear as a concrete on-screen object:

- Short form (≤300s): each motif appears in at least 2 shot prompts (verbatim or near-synonym).
  Grounding count < 2 → **CRITICAL**.
- Long form (>300s): each motif at least 5 times. < 5 → **WARNING**.
- Grounding must be a shootable concrete image, not abstract mention. E.g. motif is "wringing an apron",
  prompt should be `"Madam Quinn repeatedly wrings the apron at her waist"`, not
  `"She nervously fidgets with her apron"`.
- `lore.imagery_system.highlight_elements` — same rules, half the threshold.

### P. Dialog-shot variety (Warning)

Episode-wide r2v dialog shots (2+ characters + explicit dialog) must have **non shot-reverse-shot ratio ≥ 30%**.

- **Shot-reverse-shot flag**: prompt contains both character names +
  framing is medium / close-up + no tracking / over-shoulder / mirror keywords.
- **Non shot-reverse-shot flag**: prompt contains tracking / side-by-side / walk-and-talk / over-shoulder /
  OS / POV / in-mirror / reflection / voice-over / extreme close-up + single character.
- Episode dialog shot count ≤ 1 → skip.
- Non shot-reverse-shot ratio < 30% → **WARNING**: list all shot-reverse-shot shot ids; suggest
  switching to dialog tools 2/3/4/5.

### Q. set_id / props reference consistency (Critical)

- Every `Scene.set_id` must exist in `movie_set.json`. Missing → **CRITICAL**.
- Every `Shot.props[]` item must exist in `props.json`. Missing → **CRITICAL**.
- A chain group whose r2v shots resolve to **mixed `set_id`** (unified lighting
  rule): **CRITICAL** — split the chain or align the set_id.
- A `Shot.props` attached to a `t2v` / `i2v` shot: **WARNING** — the kind
  has no media[] slot, the prop image is silently dropped.

### R. Video provider compatibility (Warning)

Check `Storyboard.provider` (or fall back to `$SPARK_VIDEO_PROVIDER`):

- Supported providers are `wan-cli`, `bl`, and `seedance2`; aliases
  normalize in the render layer. Unknown providers are **CRITICAL**.
- For `wan-cli`, verify explicit reference numbers match the actual
  `Image N / Video N / Audio N` upload order. Warn when an r2v shot exceeds
  10 images, 5 videos, or 5 audios. Because the active Wan commands do not use
  a separate negative-prompt flag, repeat negative constraints as concrete
  positive-prompt guidance.
- For `bl`, account for HappyHorse's narrower reference/continuity features;
  do not assume reference voice or first-frame chaining on r2v.
- Wan 2.7 is selected inside `wan-cli`; do not treat it as a provider name.
- For `seedance2`, require Ark-compatible URLs/assets for local video inputs;
  local image and audio references may be embedded by the adapter.

## How to run

```bash
# Pre-checks (read everything)
cat projects/$SPARK_VIDEO_PROJECT/lore.md
cat projects/$SPARK_VIDEO_PROJECT/episode-$SPARK_VIDEO_EPISODE/storyboard.json | jq .
cat projects/$SPARK_VIDEO_PROJECT/episode-$SPARK_VIDEO_EPISODE/script.md
cat projects/$SPARK_VIDEO_PROJECT/episode-$SPARK_VIDEO_EPISODE/cast.json | jq .
cat projects/$SPARK_VIDEO_PROJECT/episode-$SPARK_VIDEO_EPISODE/movie_set.json | jq .
cat projects/$SPARK_VIDEO_PROJECT/episode-$SPARK_VIDEO_EPISODE/props.json | jq .
```

Then apply the checklist above systematically. Write report to
`projects/<p>/<ep>/reviews/vfx-review.md` and print summary to user.

If verdict is ❌ BLOCK, the producer routes the report to the director
skill for fixes. After fixes, re-run validate + this skill until verdict is
✅ or ⚠️.

## DON'Ts

- ❌ Don't modify `storyboard.json`. You review; the director fixes.
- ❌ Don't run `render_shot.py`. You're pre-render QA.
- ❌ Don't rewrite prompts. Describe what's wrong and suggest a fix direction.
- ❌ Don't block on suggestions — only block on criticals.
- ❌ Don't skip the checklist sections that look "obvious" — those are
  exactly the ones that drift through to render and waste budget.
