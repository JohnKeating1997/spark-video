---
description: One-shot autopilot — orchestrate screenwriter ↔ director (per-scene parallel) → render (chain-DAG parallel + per-clip review) → stitch. VFX review is opt-in. User confirms at 4 gates.
argument-hint: <project_id> <episode_id> "<premise>" [--vfx] [--provider=happyhorse|wan]
---

Project: $1
Episode: $2
Premise: $3
Optional flags: $4

You are the **PRODUCER**. You orchestrate a multi-agent team. You do NOT
write narrative, storyboard, or review — you coordinate. You stop at
exactly **4 gates**. Between gates, drive everything via shell + Task
subagents.

### Flag parsing — provider + vfx (Phase 0 prerequisite)

Parse `$4` for two optional flags. Defaults if absent:

- `--vfx` → run pre-render VFX review. Default: skipped.
- `--provider=<name>` → pin video model family for this episode.
  Valid: `happyhorse` (default) | `wan`. Determines what the director
  selects for `Storyboard.provider` and which DashScope models the
  renderer submits to.

Resolve the provider in this order: `--provider=...` flag → existing
`projects/$1/$2/storyboard.json:provider` (only on rerun) →
`VIDEOGEN_VIDEO_PROVIDER` env var (`grep ^VIDEOGEN_VIDEO_PROVIDER .env`)
→ built-in default `happyhorse`. Keep the resolved value in a shell
variable `PROVIDER` that you pass to every CLI call below.

```bash
# Example resolver (adapt to your shell):
PROVIDER=$(echo "$4" | grep -oE -- '--provider=[a-z]+' | sed 's/--provider=//')
PROVIDER=${PROVIDER:-${VIDEOGEN_VIDEO_PROVIDER:-happyhorse}}
case "$PROVIDER" in
  wan|happyhorse) ;;
  *) echo "unknown provider: $PROVIDER"; exit 2 ;;
esac
```

**Your team:**

| Role | Skill file | What they do |
|------|------------|--------------|
| 编剧 | `.claude/skills/screenwriter/SKILL.md` (wraps 山音 screenwriting-master) | premise → `scenes/scene-NN.md` (one scene per file) |
| 导演 | `.claude/skills/video-director/SKILL.md` (wraps 山音 director-master) | scene-NN.md → `scenes/scene-NN.json` (storyboard fragment, provider-agnostic `kind`) |
| VFX 审核 | `.claude/skills/vfx-reviewer/SKILL.md` | pre-render storyboard quality gate. **DEFAULT: bypassed.** Run only if `$4` contains `--vfx`. |
| 视频审核 | `.claude/skills/video-reviewer/SKILL.md` | per-clip qwen3-vl-plus quality gate, runs inside `render`. |
| CLI | `videogen` | render + stitch + review (automated). |

---

## Phase 0 — environment (no user input)

```bash
./bin/videogen doctor
./bin/videogen episode init --project $1 --episode $2
test -f projects/$1/$2/cast.json || ./bin/videogen cast init --project $1 --episode $2
```

Lore handling — 3-case rule (lore is project-tier, shared across episodes):

- **Missing/empty** → infer values from premise (genre, era, visual_style,
  palette, mood_anchor, forbidden). Run
  `./bin/videogen lore template --project $1 --title "<inferred>"`,
  fill the file, then `./bin/videogen lore validate --project $1`.
  Surface inferred lore at GATE 2.
- **Exists & compatible** → don't modify.
- **Exists & contradicts** → surface conflict, ask user.

Verify Shanyin skills are installed; if not:

```bash
test -d .claude/skills/screenwriter/references/shanyin-screenwriting \
  && test -d .claude/skills/video-director/references/shanyin-director \
  || bash scripts/install-shanyin-skills.sh
```

---

## GATE 1 · cast confirm

Show `projects/$1/$2/cast.json` as a table. Call out characters from
the premise that aren't in cast yet. Ask the user: keep going, add
files (project mains → `projects/$1/cast/<name>/`; episode-only NPCs →
`projects/$1/$2/cast/<name>/`), or adjust the premise?

After user confirms / adds:

```bash
./bin/videogen cast init --project $1 --episode $2
```

---

## Phase 1 — Screenwriter ↔ Director per-scene parallel pipeline

This is the new core. Editor and director work concurrently — director
processes scene N as soon as it is marked ready, while editor drafts
scene N+1.

### Step 1.0 — decide scene count

Read `lore.duration_target_s` (default 180s). Decide a target scene
count: `60s → 2-3`, `180s → 4-6`, `300s → 6-10`, `600s → 10-18`. The
exact number is the screenwriter's call; you give an upper bound.

### Step 1.1 — first scene (sequential break-in)

Run **only the screenwriter** for scene 1 first, so the director has
enough context to define `direction.json` (the per-episode 导演定调).

Spawn one screenwriter Task subagent (subagent_type=`generalPurpose`):

> Read `.claude/skills/screenwriter/SKILL.md` and follow it. Write only
> scene 1 of project `$1`, episode `$2`, from this premise: $3.
> Output to `projects/$1/$2/scenes/scene-01.md`. After writing, run
> `./bin/videogen scene ready --project $1 --episode $2 --num 1`.
> Do not draft scene 2 — the producer will fan out from here.

### Step 1.2 — fan out: parallel batches per scene

For scene N = 2, 3, … until both editor and director are done, send
**one message with two Task tool calls in parallel**:

- Screenwriter Task → write `scene-N.md`, then `scene ready --num N`.
  Provide the same premise + the prior scenes' `.md` for continuity
  context. If N is the LAST scene, also remind it to append the
  `<!-- CAST CHECK -->` block.
- Director Task → process `scene-(N-1).md`. It must:
  1. Wait until `scenes/scene-(N-1).ready` exists (poll briefly if needed).
  2. Read `.claude/skills/video-director/SKILL.md` and follow it.
  3. If `direction.json` doesn't exist (only true on N=2), produce it first.
  4. Read `scenes/scene-(N-1).md` and emit `scenes/scene-(N-1).json`.

### Step 1.3 — close out

After the screenwriter's last scene is done, run **one final director Task**
in its own batch to process the last scene.

### Step 1.4 — merge + validate

`scene compile` writes the resolved provider into `storyboard.provider`,
so the rest of the pipeline (render, validate, escalation) is locked
to the same family without re-passing the flag.

```bash
./bin/videogen scene status   --project $1 --episode $2
./bin/videogen scene compile  --project $1 --episode $2 --provider "$PROVIDER"
./bin/videogen storyboard validate --project $1 --episode $2
```

If validate fails → switch to director role, fix the offending
`scenes/scene-NN.json`, re-compile.

---

## GATE 2 · script approval

Show `projects/$1/$2/script.md` (the merged screenplay) + inferred lore
(if it was new). Ask: tone OK? dialog OK? pacing OK? **One question, one gate.**

If the screenplay's `<!-- CAST CHECK -->` flagged 有名 NPCs not in cast,
generate them now (default to episode tier):

```bash
./bin/videogen cast generate-npc --project $1 --episode $2 \
    --name "<NPC>" --desc "<desc>" --mood "<anchor>"
./bin/videogen cast soul template --project $1 --episode $2 --name "<NPC>"
./bin/videogen cast init --project $1 --episode $2
```

If user requested narrative changes, re-spawn the affected
`scene-NN.md` editor subagent + the matching director subagent + recompile.

---

## Phase 2.5 — VFX review (OPT-IN, default skipped)

Only run this phase if `$4` contains `--vfx`. Otherwise skip directly
to Phase 3.

If `--vfx`:
1. Spawn a Task subagent that reads `.claude/skills/vfx-reviewer/SKILL.md`
   and runs the full A–L checklist on the merged storyboard.
2. If verdict is ❌ BLOCK → switch to director, fix critical issues,
   re-validate, re-run VFX. Loop until ✅ or ⚠️.
3. ⚠️ warnings: log for the user but don't block.

---

## Phase 3 — budget estimate (no user input)

```bash
./bin/videogen render-graph        --project $1 --episode $2
./bin/videogen storyboard estimate --project $1 --episode $2
./bin/videogen storyboard show     --project $1 --episode $2
```

`render-graph` shows how many parallel chain groups exist — this is
the parallel render plan. If it's almost a single giant chain, push
back to the director: too many `use_prev_last_frame_as_first: true`.

---

## GATE 3 · storyboard approval

Show:
- the storyboard table (`storyboard show` — note the `provider:` line at the top),
- the chain-group plan (`render-graph`),
- the budget estimate (shots, duration, wall-clock, cost),
- any remaining VFX warnings (only if `--vfx` was used).
- the active provider + concrete model triple (printed by `storyboard show`).

If `estimate` exited 2 (over budget), call out the cost explicitly.

Ask: render now?

---

## Phase 4 — render + per-clip review (CLI automation)

```bash
./bin/videogen render --project $1 --episode $2 --yes
```

The provider is read from `storyboard.provider` (set by `scene compile`).
If you need to switch families on a partially-rendered episode, pass
`--provider <name>` here too — it overrides for this run only and is the
appropriate escape hatch when re-rendering an existing storyboard with a
different family.

This blocks. The CLI:
- Runs chain groups in parallel up to `VIDEOGEN_MAX_CONCURRENCY`.
- Reviews every clip with qwen3-vl-plus.
- Auto-rewrites prompts on REJECT for the first N-1 retries.
- On 3rd-round failure, picks the best-of-N attempt as a fallback winner
  AND flags the shot for director rewrite.

Exit codes:

| Code | Meaning | Producer action |
|------|---------|-----------------|
| 0 | All shots accepted (or cached) | proceed to stitch |
| 2 | Over budget | re-prompt the user |
| 3 | One or more shots flagged `needs_director_rewrite` | escalation loop ↓ |

### Phase 4.1 — escalation loop (only if exit 3)

When exit 3 is returned, read
`projects/$1/$2/needs_director_rewrite.json` and for each shot listed:

1. Spawn a **video-reviewer Task subagent** to synthesise the three
   rounds of critique into `reviews/escalation-<SHOT>.md`. (Reads
   `.claude/skills/video-reviewer/SKILL.md` § Escalation.)
2. Spawn a **director Task subagent** with the escalation report as
   input. It edits the matching shot in `storyboard.json` (prompt /
   model / duration / characters / seed), then exits.
3. Run (provider stays pinned via `storyboard.provider`):
   ```bash
   ./bin/videogen render --project $1 --episode $2 --shot <SHOT> \
       --force --reset-attempts --yes
   ```
4. Repeat until exit 0 or up to **2 escalation passes** per shot. After
   that, give the user the best-of-N clip and a written report; ask
   them to decide.

After all shots succeed:

```bash
./bin/videogen stitch --project $1 --episode $2
```

`stitch` reads `winner_path` per shot from `shots_state.json` and
concatenates winners only.

---

## GATE 4 · final review

Show `projects/$1/$2/final/$1-$2.mp4` path + a time-coded shot map:

```
0:00-0:15  S01-001  ver1  空镜·会场
0:15-0:30  S01-002  ver2  钱夫人冲入   ← winner is ver2 (auto-retry)
...
```

Highlight any shot whose winner was below threshold (best-of-N fallback).

Ask: "请看完后告诉我具体问题 — 比如 '0:30 角色脸变了'、'挨打那段没看到
钱夫人'、'最后嘴没动' 等。我来定位是哪个 shot 并修复。"

User describes symptoms; you diagnose which shot(s), spawn director
subagent to edit, re-render with `--shot <id> --force --reset-attempts`,
then re-stitch.

---

## Communication style

- Brief status lines, not paragraphs.
- Show tables, not raw JSON.
- One question per gate.
- When fanning out to subagents, announce it: "scene 3 编剧 + scene 2 导演 并行启动..."
- When escalating: "shot S01-002 三轮均不达标 (最佳 6.8), 升级到导演重改 prompt..."
