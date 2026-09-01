---
name: spark-video
description: Install, set up, diagnose, and run the full spark-video AI video production pipeline from premise to screenplay, storyboard, render, review, and final mp4. Use when the user mentions spark-video, wants to make an AI video, episode, short, ad, or recap, or asks to install, repair, or run the spark-video workflow.
---

# Runtime workspace

Keep the shell's current working directory as the user's video workspace.
Do not `cd` into the installed skill directory for normal operation. Run
scripts by absolute path from the resolved skill directory, for example:

```bash
export SPARK_VIDEO_SKILL_DIR="$SKILL_DIR"
"$SPARK_VIDEO_SKILL_DIR/scripts/doctor.sh" --quick --json
uv run "$SPARK_VIDEO_SKILL_DIR/scripts/scaffold.py" episode --init
```

On native Windows PowerShell, use the matching `.ps1` entry point:

```powershell
$env:SPARK_VIDEO_SKILL_DIR = $SKILL_DIR
& "$env:SPARK_VIDEO_SKILL_DIR\scripts\doctor.ps1" -Quick -Json
uv run "$env:SPARK_VIDEO_SKILL_DIR\scripts\scaffold.py" episode --init
```

When examples in this skill or spark-video references show
`uv run scripts/...` or `./scripts/...`, interpret them as the same script
under `$SPARK_VIDEO_SKILL_DIR`. On native Windows, use the corresponding
PowerShell wrapper when one exists (`doctor.ps1`, `install-deps.ps1`, or
`bl.ps1`); Python scripts continue to run through `uv run`.

Runtime state lives under the current working directory:
- `projects/` (or `$VIDEOGEN_PROJECTS_DIR`) for episode state and outputs.
- `.env` for local configuration and secrets.
- `.spark-video/references/shanyin/` for optional Shanyin craft references,
  unless `$SPARK_VIDEO_SHANYIN_DIR` is set.

# Mandatory lightweight preflight

Run the quick doctor once per user request that invokes spark-video,
before the first spark-video script call:

```bash
preflight_json="$("$SPARK_VIDEO_SKILL_DIR/scripts/doctor.sh" --quick --json)"
```

On Windows PowerShell, use:

```powershell
$preflightJson = & "$env:SPARK_VIDEO_SKILL_DIR\scripts\doctor.ps1" -Quick -Json
```

If the JSON has `"ok": true`, continue silently; do not paste the full
JSON into the conversation. Optional Shanyin warnings do not block use.
Do not repeat the quick doctor inside the same user request unless an
install or repair command was run, or a dependency-related command fails.

Before the first `wan` generation command in a session, run `wan --version`
and `wan update --check --output json`. If an update is available, ask the
user before running `wan update --output json`; never update silently.

### Display generated images

After any image-generation call (including calls delegated to another agent),
return the generated local image paths to the host agent. When using
`scripts/generate_asset.py`, its JSON output includes `savedFiles` and a ready-
to-render `preview_markdown` field. The host agent should include
`preview_markdown` unchanged in its final response so Codex can display the
images immediately after generation. If another agent performs the generation,
it must return the same absolute paths or Markdown previews through its result;
task IDs or remote URLs alone are not sufficient for local display.

Download and preserve every returned candidate. The Agent must assess the
candidates and record one reasoned default with `scaffold.py asset-recommend`.
That default is immediately usable by manifests and downstream stages; asset
review is not a blocking user-confirmation gate. Rebuild Viewer, tell the user
that every default can be changed there, and apply any later Viewer handoff with
`scaffold.py asset-select`. Never rename a candidate as a shortcut or delete
unselected files. Independent asset batches may generate in parallel and may
be presented together in Viewer.

If `"ok": false`, or if the user asks to install, set up, repair, or
diagnose spark-video, read `$SPARK_VIDEO_SKILL_DIR/references/setup.md`, run
`"$SPARK_VIDEO_SKILL_DIR/scripts/doctor.sh" --install-plan --json`, ask
before each command, then re-run the quick doctor.

# Producer Skill — spark-video one-shot production

You are the **producer** of the spark-video pipeline. You orchestrate five
bundled stage instruction files and the deterministic scripts under `scripts/`.
They are internal references, not separately registered skills: never ask the
host Skill tool to invoke `spark-video-cast`, `spark-video-screenwriter`,
`spark-video-director`, `spark-video-vfx-review`, or
`spark-video-clip-review`. Before performing or delegating a stage, read and
follow its corresponding file:

- Screenwriting: `references/spark-video-screenwriter.md`
- Direction/storyboarding: `references/spark-video-director.md`
- Cast, set, and prop assets: `references/spark-video-cast.md`
- Optional pre-render VFX review: `references/spark-video-vfx-review.md`
- Per-clip review and retry: `references/spark-video-clip-review/instructions.md`

Users invoke the root skill when
they want to produce one episode end-to-end with minimal hand-holding.

Set env vars at the top of every run:
```bash
export SPARK_VIDEO_PROJECT=<project_id>
export SPARK_VIDEO_EPISODE=<NN>
export SPARK_VIDEO_PHASE=producer
# SPARK_VIDEO_PROVIDER defaults to "wan-cli"; bundled alternatives:
# bl, seedance2
```

## Inputs from the user

When invoked, the user gives you:
1. **project_id** (e.g. `hf`, `demo`)
2. **episode** (e.g. `001`)
3. **premise** — one paragraph story idea. Capture this verbatim and
   persist it to `projects/<p>/initialPrompt.md` (or
   `projects/<p>/<ep>/premise.md` for per-episode overrides) in Step 0
   — see preflight. If the user attached reference media, the same Premise
   file must also retain an ordered reference manifest. `viewer.html` reads it
   back from there.
4. (optional flags) `--vfx` to opt into pre-render VFX review,
   `--mode=drama|narration`, and
   `--audio-mode=presenter_voiceover|native_dialogue|hybrid`.

## User-confirmation checkpoints

The user owns creative decisions and render authorization. GATE 0 may be
pre-satisfied only when story mode, audio mode, and canonical visual medium
were explicit; GATE 0.5 is
conditional on available BGM. New cast, set, or prop images receive an Agent
default and appear in Viewer for optional changes; they do not add a blocking
checkpoint. Never skip GATE 1-4. `--vfx` enables an extra review and does not
waive a gate.

| Gate | When | What you show | What you ask |
|---|---|---|---|
| **GATE 0** | Before any work, unless story mode, audio mode, and visual medium are all explicit | Story format, whole-episode audio contract, and canonical visual medium | "Story format and audio source? Confirm visual medium: live action, 2D animation, 3D animation, stop motion, or an explicitly bounded mix." |
| **GATE 0.5** | After GATE 0, only if `projects/<p>/bgm/` or `projects/<p>/<ep>/bgm/` exists with audio files | List of available BGM tracks | "Post BGM: off, one global track, or scene-selected tracks? Separately, allow model-generated BGM? (default: no; ambience/effects may remain)" |
| **ASSET REVIEW** *(non-blocking)* | After all independent cast/set/prop generations | `viewer.html` showing every downloaded candidate and the Agent's active default for each asset | "Defaults are ready and production will continue. You can change any asset in Viewer or ask to regenerate it." |
| **GATE 1** | After screenwriter finishes all scenes/scene-NN.md and you've compiled into `script.md` | `viewer.html` (auto-opened) showing premise + script + cast/sets/props | "Script OK? Approve to proceed to storyboarding, or describe changes." |
| **GATE 2** | After director finishes all scenes/scene-NN.json and you've compiled+validated into `storyboard.json`. If `--vfx`, follow the bundled VFX-review instructions first and show the report. | `viewer.html` (auto-opened) showing storyboard summary + scenes + shots | "Storyboard OK? Approve to render, or describe changes." |
| **GATE 3** | After all shots rendered + reviewed (winner_version set for each, escalations resolved) | `viewer.html` (auto-opened) showing all clips + reviews + winner highlights | "Renders OK? Approve to stitch final, or specify shots to re-render." |
| **GATE 4** | After stitch completes | `viewer.html` (auto-opened) showing final mp4 + full production archive | "OK to finalize? Want to re-render any shots or adjust BGM mix?" |

At any gate, if user says "no", listen to their feedback, do the edits,
re-show, ask again.

Immediately after the user selects an audio mode that uses post TTS
(`presenter_voiceover` or `hybrid`), run:

```bash
"$SPARK_VIDEO_SKILL_DIR/scripts/doctor.sh" --quick --json --narration
```

On Windows PowerShell, run
`& "$env:SPARK_VIDEO_SKILL_DIR\scripts\doctor.ps1" -Quick -Json -Narration`.

If it reports missing `bl` or `bl-auth`, run the matching narration-aware
install plan, explain that bl is needed only for narration TTS, and ask before
each install/auth command. Do not continue to script generation until the
narration preflight returns `"ok": true`:

```bash
"$SPARK_VIDEO_SKILL_DIR/scripts/doctor.sh" --install-plan --json --narration
```

On Windows PowerShell, run
`& "$env:SPARK_VIDEO_SKILL_DIR\scripts\doctor.ps1" -InstallPlan -Json -Narration`.

## Pipeline flow (with parallelism markers)

```
                  ╔══════════════════════════════════════════╗
                  ║  YOU (spark-video / producer)            ║
                  ╚══════════════════════════════════════════╝
                                  │
                            [GATE 0: mode]
                                  │
                       [GATE 0.5: BGM, if applicable]
                                  │
       ┌──────────────────────────┴───────────────────────────┐
       │  Zone 1 — per-scene parallel                          │
       │  ┌────────────────────┐    ┌─────────────────────┐   │
       │  │ spark-video-       │═══▶│ spark-video-        │   │
       │  │  screenwriter      │    │  director           │   │
       │  │ scene-NN.md        │    │ scene-NN.json       │   │
       │  └────────────────────┘    └─────────────────────┘   │
       │  Producer fans out N copies in parallel per ready    │
       │  scene (cap: SPARK_VIDEO_MAX_CONCURRENCY)            │
       └──────────────────────────┬───────────────────────────┘
                                  │
                       uv run scripts/storyboard.py compile
                                  │
                            [GATE 1: script.md]
                                  │
                            [GATE 2: storyboard.json]
                                  │
            optional: spark-video-vfx-review (when --vfx)
                                  │
       ┌──────────────────────────┴───────────────────────────┐
       │  Zone 2 — render chain groups in parallel             │
       │  uv run scripts/storyboard.py graph                  │
       │    → [[S01-001,S01-002], [S02-001], ...]              │
       │  Fan out one spark-video-clip-review per chain group; │
       │  inside each group, sequential.                       │
       │                                                       │
       │  Zone 3 — per-clip review + retry (inside clip-review)│
       │   render → optional bl review → ACCEPT / retry       │
       │   exhausted retries → escalate to spark-video-director│
       └──────────────────────────┬───────────────────────────┘
                                  │
                            [GATE 3: clips]
                                  │
                       uv run scripts/stitch.py
                                  │
                            [GATE 4: final mp4]
```

## Step-by-step procedure

### Step 0 — preflight
```bash
"$SPARK_VIDEO_SKILL_DIR/scripts/doctor.sh" --quick --json  # follow references/setup.md if ok=false
uv run "$SPARK_VIDEO_SKILL_DIR/scripts/scaffold.py" episode --init

# Persist the user's raw premise to disk BEFORE any other work. This is
# the single source of truth for "what did the user actually ask for?"
# and is read back by scripts/build_viewer.py to populate the Premise
# section of viewer.html. Without this file viewer.html will show
# "(no initialPrompt.md / premise.md found …)" forever.
#   Project-wide premise (recommended for the first episode of a series):
#     projects/<p>/initialPrompt.md
#   Per-episode premise override (use when this episode departs from the
#   series-level premise, e.g. a spin-off or recap):
#     projects/<p>/<ep>/premise.md
# Keep the user's prompt verbatim — do NOT summarise or translate it. If the
# request includes attached media, append an ordered "User-provided references"
# manifest after the verbatim text. Record the attachment path exactly as
# received, its user-stated role, and (after asset generation) the stable source/
# copy. Do not add inferred appearance descriptions to this manifest.
premise_path="projects/$SPARK_VIDEO_PROJECT/initialPrompt.md"
if [ ! -s "$premise_path" ]; then
  mkdir -p "$(dirname "$premise_path")"
  cat > "$premise_path" <<'PREMISE_EOF'
<paste the user's premise here, verbatim, including any constraints,
references, character names, tone notes — anything they said about
what they want this episode to be>

## User-provided references

- Image 1
  - Preview: ![Image 1](<cast/<name>/source/source-01.<ext>>)
  - Original attachment: `<path exactly as received>`
  - Stored source: `projects/<p>/cast/<name>/source/source-01.<ext>`
  - User-stated role: `<for example: main character reference>`
PREMISE_EOF
fi

# Check lore.md exists; if not:
test -f projects/$SPARK_VIDEO_PROJECT/lore.md || \
  uv run scripts/scaffold.py lore --title "<premise's first noun phrase>"
# Tell user lore.md was scaffolded with mood_anchor=TBD; ask to fill it,
# or derive it from the premise using the host agent's own reasoning.
```

### Step 1 — GATE 0: story format + audio contract
Unless `--mode` was passed, present the two story formats:
- **drama** (short drama, default) — action/conflict-led scenes whose shot
  durations are chosen from the content. Use for 2–5 min original shorts.
- **narration** (voiceover-led structure) — a sequence of short explanatory beats.

Then choose exactly one audio strategy:

- **presenter_voiceover** — recommended for explainers/tutorials. One named
  presenter and one fixed TTS voice across every spoken shot; all model audio
  is removed; every shot carries presenter speech; generated captions are forbidden.
- **native_dialogue** — Wan generates all character speech; no post TTS.
- **hybrid** — only when the user explicitly requests mixed sources. Every shot
  must declare its source; never infer a hybrid merely from shot role.

Also resolve exactly one canonical visual medium and persist it to
`lore.visual_medium` before generating any cast, set, prop, or storyboard panel:

- `live_action` — photographic/live-action realism.
- `2d_animation` — illustration, cartoon, anime, cel, or hand-drawn animation.
- `3d_animation` — 3D, CG, CGI, or computer-generated animation.
- `stop_motion` — puppet, clay, miniature, or stop-motion animation.
- `mixed` — only when the user names the medium boundary between concrete
  elements. Every affected shot must restate that boundary.

Legacy `illustration` normalizes to `2d_animation`. Bare `animation`,
`animated`, or `动画` is ambiguous: ask whether the user means 2D, 3D, or stop
motion instead of guessing. Store the concrete production treatment in
`visual_style`. Keep `mood_anchor` global and limited to lighting, palette,
contrast, texture, and atmosphere; never put a named character's face, hair,
costume, accessories, or body traits there. Those belong to the cast card, and
recurring composition emphasis belongs to `imagery_system.highlight_elements`.

For presenter voiceover, also record `presenter` and `voice`. Do not proceed
with placeholders. Persist the choice to
`projects/<p>/<ep>/audio-config.json`, then pass the complete contract to
screenwriter and director. `storyboard.py compile` reads that file; explicit
CLI audio flags override it.

```json
{
  "mode": "presenter_voiceover",
  "presenter": "xiaoya",
  "voice": "xiaoya-voice",
  "model_audio_policy": "strip_all",
  "subtitle_mode": "off"
}
```

Prompt handoff rules:

- Keep the director's `prompt` visual-only for `post_tts`; store the spoken line
  only in `speech_text`. The render adapter adds the no-speech/no-subtitle guard.
- Use `allow_generated_text: false` unless the user explicitly approves exact
  visible text. Watermarks remain outside this policy and outside review scope.
- For Wan3.0 shots longer than 15s, require `long_take_reason` plus a contiguous
  timed action plan. At 15s or below, add `beats` only when precise continuous
  choreography benefits from explicit contact, occlusion, environmental
  response, or camera/subject synchronization. Never prescribe a beat count;
  content owns the segmentation and the renderer only checks timeline integrity.
- Require `camera_path` and `end_composition` on every newly authored shot.
  Write `camera_path` with the Director's professional camera grammar: lens,
  opening geometry, support/subject relationship, one continuous path, physical
  dynamics, and landing position.
  Together with bound cast/set/prop/voice/previous-frame references, compile
  the final Wan prompt as: reference contract, visual action, timed beats,
  camera path, ending composition, audio policy, constraints.
- Let the Director Agent choose the shortest content-appropriate integer
  `duration`; 5/15/30 are not presets. Start from a 6-8s prior: use 2-5s for a
  simple insert/reaction, 6-10s for most shots, 11-15s only when performance,
  speech, or camera travel needs it, and 16-30s only as a justified exceptional
  long take. Treat the model limit as a ceiling and shorten under-filled shots.
- At GATE 2, use Viewer to compare the prompt contract, visual prompt, static
  prompt, post-voice script, and (after rendering) the literal prompt sent to Wan.

### Step 2 — GATE 0.5: BGM (only if folder exists)
```bash
test -d projects/$SPARK_VIDEO_PROJECT/bgm || \
  test -d projects/$SPARK_VIDEO_PROJECT/episode-$SPARK_VIDEO_EPISODE/bgm || skip
ls projects/$SPARK_VIDEO_PROJECT{,/episode-$SPARK_VIDEO_EPISODE}/bgm/*.{mp3,wav,m4a,flac,ogg,aac} 2>/dev/null
```

Present tracks, ask user for `mode` + `forbid-model-bgm`. Record into
`projects/<p>/<ep>/bgm-config.json` (the compile step reads this and
writes `Storyboard.bgm`).

### Step 3 — asset generation, defaults, then manifests
If the user's premise mentions new characters/locations not present, read and
follow `references/spark-video-cast.md` first to scaffold and generate
cast reference sheets BEFORE
launching the screenwriter.

After generation, inspect each candidate set and record one reasoned default
with `scaffold.py asset-recommend`. Rebuild `cast.json`, `movie_set.json`, and
`props.json`, then run `build_viewer.py` while all candidates are still present.
Tell the user that the defaults are already active and that they may change any
one in Viewer or state a filename directly; do not wait for a response before
screenwriting. Apply later user choices with `scaffold.py asset-select`, then
rebuild the affected manifest and Viewer. Do not rename a candidate as a
shortcut or clean up the remaining candidates.

```bash
uv run scripts/scaffold.py cast-init           # build cast.json
uv run scripts/scaffold.py set-init            # build movie_set.json
uv run scripts/scaffold.py prop-init            # build props.json
```

When a character comes from a user-supplied image, visually inspect the actual
local file and preserve only visible identity, hair, costume, accessories, body
type, and apparent age. Pass it to `generate_asset.py cast --source-image ...`;
never copy the original into the cast folder root or treat it as the completed
cast asset. The original is provenance under `cast/<name>/source/`. Only an
Agent default or a later user override recorded through the asset sidecars may
be used by downstream storyboards and video renders. Wan reference tags follow the
account site: CN uses `@图片1`, international uses `@Image1`; creative prompt
language does not switch this syntax.

### Step 4 — Zone 1: per-scene editor ↔ director parallel

Fan out the screenwriter on scenes 1..N (number from premise length —
see screenwriter pacing table). As each `scene-NN.md` becomes ready
(touched `scene-NN.ready` sentinel), fan out the director on it in
parallel with screenwriter drafting scene N+1.

Implementation in your harness:
- If harness supports parallel subagent invocation, use it: spawn one
  screenwriter subagent per scene, plus one director subagent waiting
  on each ready sentinel.
- If sequential, loop scenes in order. Still cheaper than rendering.

Cap: `SPARK_VIDEO_MAX_CONCURRENCY=4` parallel subagents at once.

When all scenes drafted + storyboarded:
```bash
uv run scripts/storyboard.py compile \
  --mode <drama|narration> \
  --video-model wan3.0 \
  --audio-mode <presenter_voiceover|native_dialogue|hybrid> \
  [--presenter <cast-name> --voice <voice-id>]
uv run scripts/storyboard.py validate
uv run scripts/storyboard.py graph
uv run scripts/storyboard.py estimate
```

### Step 5 — GATE 1: script.md
```bash
uv run scripts/build_viewer.py            # opens viewer.html in browser for review
```
Show the user the merged `script.md` — point them to the viewer.html
that just opened (it shows premise, lore, direction, script, cast,
sets, props at this stage). Wait for approval.

If they want changes, identify which scene(s), follow the bundled screenwriter
instructions for those scenes, then re-compile.

### Step 6 — GATE 2: storyboard.json
Print the storyboard summary:
- Total shots, breakdown by kind (t2v / i2v / r2v)
- Parallel chain group count (from `storyboard.py graph`)
- Estimated total duration of final video
- Estimated render workload (from `storyboard.py estimate`)
  - If estimate exits 2 (over `SPARK_VIDEO_LONG_CONFIRM_S`), surface
    the warning explicitly.

`storyboard.py estimate` is a workload and duration estimate, not monetary
accounting. `wan credits` reports balance, not a per-task price ledger. Quote a
currency/credit cost only when the user supplies an authoritative current rate
or a current Wan source exposes one; otherwise state that cost is unavailable.

If `--vfx`, follow `references/spark-video-vfx-review.md` and show its
report alongside.

```bash
uv run scripts/storyboard.py animatic --generate
uv run scripts/storyboard.py validate
uv run scripts/build_viewer.py            # opens viewer.html — now includes scenes + shots
```

When only specific shots changed, regenerate only those references. Never use
an unscoped `--force` for a local shot revision:

```bash
uv run scripts/storyboard.py animatic --generate --force \
  --shot S02-003 --shot S03-002
```

Show the user `projects/<p>/<ep>/storyboard-panels/`: each clip gets four
static storyboard candidates by default. The viewer presents them as a
contact sheet with Take 01 provisionally selected. After the user keeps or
changes one take per shot, persist the attached viewer decisions with one or
more `--select SHOT=CANDIDATE` arguments.
These images are the cheap visual approval gate before expensive video
rendering, and `render_all.py` passes only the selected image as reference
media for that same clip.

The viewer also attaches the current choices compactly in the `sv` query
parameter. Values are 1-based candidate numbers in storyboard shot order
(`sv=1.2.1` means Take 01, Take 02, Take 01). At GATE 2, ask the user to
review and confirm normally. When the host provides the current viewer URL,
their regular confirmation reply is enough: map those numbers back through
`panels.json` and persist the choices with `--select`. Do not require a special
"selection ready" message or ask the user to paste a command.

After `animatic --confirm`, the viewer keeps all candidates visible for audit
but disables candidate switching and marks the chosen take as Gate-locked. If
the user requests a change, run `animatic --unconfirm`, rebuild the viewer,
and re-render any already-generated shots whose reference selection changed.

Wait for approval of both the storyboard breakdown and the per-clip
static reference images. If approved:

```bash
uv run scripts/storyboard.py animatic --select shot-001=shot-001-candidate-02
uv run scripts/storyboard.py animatic --confirm
uv run scripts/gate.py check storyboard
```

The approved storyboard reference image is never used as `first_frame`.
It is passed to the active Wan model as ordinary reference media. On Wan3,
previous-last-frame and optional ending-frame inputs are added to the same Omni
request; the compiled prompt labels their target opening/ending composition
roles without dropping storyboard/cast/set/prop references.

If they want changes, route feedback to the director instructions in
`references/spark-video-director.md` for the specific scenes, then
re-compile.

### Step 7 — Zone 2 + 3: render all shots

Use `render_all.py` for batch rendering — it handles chain-group
parallelism, media resolution, first-frame chaining, and per-clip
auto-review internally. **Never manually fan out `render_shot.py`
calls or write ad-hoc batch scripts.**

```bash
# Full reset — re-render everything from scratch:
uv run scripts/render_all.py --reset --ratio 9:16

# After prompt changes — only re-render shots that were REJECT:
uv run scripts/render_all.py --rejected-only

# Re-render specific shots:
uv run scripts/render_all.py --shot S01-002 --shot S03-004

# Only re-render FAILED or winner-less shots:
uv run scripts/render_all.py --failed-only
```

`render_all.py` handles:
- Chain-group-aware parallelism with previous-last-frame Omni guidance on Wan3
- Automatic media resolution from per-clip storyboard references,
  `cast.json` / `movie_set.json` / `props.json`
- Optional per-clip bl review via `render_shot.py` (when bl is authenticated;
  otherwise the review is marked `SKIPPED` and the clip is promoted)
- Winner promotion on ACCEPT
- `viewer.html` refresh after each shot

The stdout JSON summary includes `rejected_shots` with each shot's
`review.critique`. The agent owns prompt rewriting for REJECTs — read
the critique, edit `scenes/scene-NN.json`, then re-run with
`--rejected-only`.

You only intervene beyond `render_all.py` when:
- Escalation: `needs_director_rewrite.json` appears. Follow
  `references/spark-video-director.md` with the escalation report, then re-render the
  affected shot(s) with `--shot <id>`.
- Hard failure: check `logs/model_calls.jsonl` to diagnose, then retry
  or escalate to the user.

### Step 8 — GATE 3: per-shot summary

```bash
uv run scripts/build_viewer.py             # opens viewer.html — all clips + reviews visible
```

Once all shots have `winner_version` set:

```bash
jq '.[] | {shot: .shot_id, ver: .winner_version,
           score: ([.attempts[]|.review.score]|max),
           below_threshold: ((.attempts[]|.review.score|select(.<7))!=null)}' \
  projects/$SPARK_VIDEO_PROJECT/episode-$SPARK_VIDEO_EPISODE/shots_state.json
```

Present the per-shot table. Flag any shots accepted below threshold
(best-of-N when retries exhausted). Ask user if any should be
re-rendered manually before stitch.

### Step 9 — stitch
```bash
uv run scripts/stitch.py --crossfade 0.5
```

`stitch.py` handles:
- Concatenating all `clips/<shot>.mp4` in shot id order
- Apply the approved `Storyboard.audio` contract: presenter voiceover strips
  model audio from every shot and uses one voice for every post-TTS segment
- Write `final/audio_manifest.json` for GATE 4 voice/source verification
- For BGM: mix `Storyboard.bgm.track` underneath dialog audio
  (EBU R128 normalized, fade in/out)
- Output to `projects/<p>/<ep>/final/<p>-<ep>.mp4`

### Step 10 — GATE 4: final review

```bash
# stitch.py already rebuilt + opened viewer.html; if stale, force refresh:
uv run scripts/build_viewer.py
```

Show:
- Final mp4 path
- Total duration (vs target)
- File size

Ask if user wants to re-render any shots or adjust BGM. If yes, loop
back to the relevant step.

## Configuration knobs (env vars)

| Var | Default | Meaning |
|-----|---------|---------|
| `SPARK_VIDEO_PROVIDER` | `wan-cli` | Video provider: `wan-cli`, `bl`, or `seedance2` (aliases: `wan`, `happyhorse`, `seedance`) |
| `SPARK_VIDEO_WAN_VIDEO_MODEL` | `wan3.0` | Uses unified Wan 3.0 Omni by default; Wan 2.7 maps generic kinds to legacy capabilities |
| `SPARK_VIDEO_MAX_CONCURRENCY` | `4` | Parallel chain groups / subagents |
| `SPARK_VIDEO_SHOT_TIMEOUT_S` | `1200` | Maximum wall time for one `render_all` shot subprocess |
| `SPARK_VIDEO_REVIEW_THRESHOLD` | `7.0` | ACCEPT cutoff for clip-review |
| `SPARK_VIDEO_MAX_RETRY` | `3` | Retry rounds per shot before escalation |
| `SPARK_VIDEO_LONG_CONFIRM_S` | `600` | Estimate exit-2 threshold (seconds of rendered video) |
| `VIDEOGEN_NARRATOR_TTS_MODEL` | `cosyvoice-v3-flash` | Narration TTS via bl; `SPARK_VIDEO_*` overrides per run |
| `VIDEOGEN_NARRATOR_VOICE` | `longanyang` | Legacy fallback only; approved `AudioPlan.voice` wins |
| `VIDEOGEN_NARRATOR_SPEECH_RATE` | `1.2` | Default speech rate (0.5–2.0); `SPARK_VIDEO_*` overrides per run |
| `SPARK_VIDEO_SHANYIN_DIR` | `$PWD/.spark-video/references/shanyin` | Optional Shanyin craft reference clone location |

## Handling user "no" at any gate

The pattern is always: **listen → identify scope → follow the right bundled
stage instructions → re-show**. Examples:

- "The script is weak — Madam Quinn needs more bite" at GATE 1 → follow
  `references/spark-video-screenwriter.md`
  with scope = which scenes, plus the user's note. Re-compile script.md,
  re-show.
- "S03-002 is too dark" at GATE 3 → don't re-render the whole
  storyboard. Just `uv run scripts/render_shot.py --shot S03-002 --force
  --reset-attempts` (auto-runs clip-review). Re-show updated shot.
- "BGM is too loud" at GATE 4 → edit `Storyboard.bgm.volume` (or
  `bgm-config.json`), re-run `uv run scripts/stitch.py`.

## DON'Ts

- ❌ Don't skip GATE 1-4. Only pre-satisfy GATE 0 when story mode, audio mode,
  and canonical visual medium are explicit; GATE 0.5 is absent when no BGM
  exists. `--vfx` adds review only.
- ❌ Don't render before `storyboard.py validate` passes. Renders are
  expensive; validation is free.
- ❌ Don't render before `storyboard.py estimate` is shown to the user
  at GATE 2. If estimate exits 2 (over budget), surface that explicitly.
- ❌ Don't call `bl` directly anywhere — always use `./scripts/bl` on
  Unix-like systems or `scripts/bl.ps1` on native Windows so the call lands
  in `logs/model_calls.jsonl`. Same rule for any subagent you spawn.
- ❌ Don't auto-accept escalations. When `needs_director_rewrite.json`
  appears, you must follow `references/spark-video-director.md` and edit the
  scene before re-rendering.
- ❌ Don't proceed past a chain group that has a hard render failure.
  Diagnose first (read logs/model_calls.jsonl).
- ❌ Don't fan out beyond `SPARK_VIDEO_MAX_CONCURRENCY`. Provider rate
  limits will spike and fail the whole batch.
- ❌ Don't write `script.md` or `storyboard.json` yourself — always go
  through `uv run scripts/storyboard.py compile` so validation runs.
- ❌ Don't start screenwriter / director / render work without first
  persisting the user's raw premise to
  `projects/<p>/initialPrompt.md` (or `projects/<p>/<ep>/premise.md`).
  Without this file `viewer.html` shows an empty Premise section and
  there is no audit trail of what the user originally asked for.
