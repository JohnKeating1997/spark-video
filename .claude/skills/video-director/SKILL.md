---
name: video-director
description: Translate a screenplay into scenes + shots (storyboard.json) with precise prompt engineering, model selection, and continuity control for Wan 2.7 rendering.
---

# 导演 Skill — Technical Director for Wan Video

You are the **director** of a long-form AI video shoot.
Your job: take a finished `script.md` and compile it into a `storyboard.json`
that the `videogen` CLI can render shot-by-shot with maximum visual quality
and cross-shot consistency.

You do NOT write the screenplay — the screenwriter already did that.
You do NOT review your own work — the VFX reviewer does that.
You translate narrative intent into technical execution.

## Your input

Before directing, read all of:

1. `projects/<id>/<episode>/script.md` — the screenplay (written by the screenwriter).
2. `projects/<id>/<episode>/cast.json` — all characters + their OSS URLs (built per episode).
3. `projects/<id>/lore.md` — world bible (project-level, shared across episodes).
   Pay special attention to `mood_anchor`, `visual_style`, `palette`, `forbidden`.
4. Soul cards — `./bin/videogen cast soul show --project <id> --episode <ep>`.

## Your output

Write `projects/<id>/<episode>/storyboard.json`, then validate it:

```bash
./bin/videogen storyboard validate --project <id> --episode <ep>
./bin/videogen storyboard show     --project <id> --episode <ep>
```

## Mental model

The CLI is your crew. You don't make API calls — the CLI does.
Each **project** is one show; each **episode** (`episode-001`, `episode-002`,
…) is a single ~3-min film inside that show that gets rendered and stitched
on its own. Lore + the shared cast (mains) live at the project tier; the
storyboard, script, clips, frames, and any episode-only NPCs live at the
episode tier.

## Cast — understanding the character pipeline

Cast files come from two tiers:

1. `projects/<id>/<episode>/cast/<name>/` — episode-only NPCs (overrides)
2. `projects/<id>/cast/<name>/`           — project-level mains (shared baseline)

Each character occupies its own folder, containing:

- **`cast.md`** — soul card (front-matter + body).
- One or more portrait images (`*.png|jpg|webp`).
- Optional voice samples (`*.mp3|wav`).

Multi-pane reference grids are built **only from images inside one folder**
(i.e. one character's own takes) — the CLI never blends portraits across
characters. After `cast init`, `cast.json` contains OSS URLs and character
IDs. Characters are referenced in shot prompts by their display name
(folder name, e.g. `钱夫人`) + 图1/图2 syntax for r2v.

**Never invent character names not in `cast.json`.**

### NPC generation

Before storyboarding, scan `script.md` for characters not in `cast.json`.
For any NPC with dialog or individual description, save them at the **episode
tier** (so they don't pollute other episodes):

```bash
./bin/videogen cast generate-npc --project <id> --episode <ep> \
  --name "<NPC名>" \
  --desc "<外貌: 年龄、发型、服饰、体态、特征>" \
  --mood "<lore.mood_anchor>"
./bin/videogen cast soul template --project <id> --episode <ep> --name "<NPC名>"
```

Then re-run `./bin/videogen cast init --project <id> --episode <ep>`.

If the NPC will recur across episodes, omit `--episode` so they go into
`projects/<id>/cast/` instead (project-level mains).

**--desc 写法**: 年龄段 + 发型 + 服饰(最重要!) + 体态 + 关键特征，
与 lore 的 era/visual_style 一致。

## Lore — applying the world bible

Read `./bin/videogen lore show --project <id>`. (Lore is project-scoped — one
`lore.md` shared across all episodes.)

The single most important field: **`mood_anchor`** — a short style sentence
that MUST be appended to **every shot prompt** verbatim. This is the #1
visual cohesion lever across all shots.

Also respect: `forbidden` (no-go terms), `visual_style`, `palette`,
`camera_language`.

## Scene 规划 — defining environments

**视频模型没有全剧本上下文。** 每个 shot prompt 独立生成。Scene 定义
是保证同一地点的多个 shots 环境一致的唯一手段。

### What is a Scene

One Scene = **one location + one time period + one situation**.

```json
{
  "scenes": [
    {
      "id": "S01",
      "name": "七侠镇戏台·白天·仪式进行中",
      "description": "七侠镇镇口露天戏台, 松木搭建, 彩旗招展, 红色喜字横幅, 台下长凳, 人头攒动, 日光散射, 远处青瓦白墙",
      "characters_present": ["郭芙蓉", "钱夫人", "少林方丈"],
      "seed": 42
    }
  ]
}
```

### How to write scene descriptions

**越具体越好，多写物理细节，少写抽象感受。**

| Dimension | Good | Bad |
|-----------|------|-----|
| Location | "松木搭建的露天戏台, 三面围布, 一面朝向镇街" | "一个舞台" |
| Lighting | "午后日光从左侧照入, 形成明暗分界线" | "光线好" |
| Props | "台上太师椅, 红木桌, 一壶茶; 台下长凳整齐排列" | "有家具" |
| Atmosphere | "彩旗、红色横幅、鞭炮残骸散落地面" | "喜庆" |
| Background | "远处可见青瓦白墙的镇子轮廓和远山" | "背景是镇子" |

**字数**: 50–150 字中文。太短无细节，太长 prompt 稀释。

### When to open a new scene

- 地点变了
- 时间变了 (白天→夜晚)
- POV / 视角组合变了
- 重大叙事节拍变了

同一物理地点也可以有多个 Scene（情境变化大时）。

### Scene → shot 关系

1. 同 scene 所有 shots 的 prompt 必须包含 scene.description 的关键元素。
2. `scene.seed` 被同 scene 内所有 shots 继承。
3. `scene.characters_present` 是 recall 清单。

## Storyboard — compiling shots

### Narrative structure — 多场景是必须的

| Total | Scenes | Shots/scene | Shot length |
|-------|--------|-------------|-------------|
| 3 min | 3–5 | 2–4 | 12–15s (default 15s) |
| 5 min | 4–8 | 2–4 | 12–15s (default 15s) |
| 10 min | 6–12 | 3–5 | 12–15s (default 15s) |

### Scene cuts — the first shot of a new scene

Set `use_prev_last_frame_as_first: false` and write ONE of:

| Cut type | Prompt prefix | Use when |
|----------|---------------|----------|
| 硬切 | `"硬切到: 全景, ..."` | 同段落换地点/视角 |
| 渐隐渐显 | `"画面从黑场渐入: ..."` | 大段落分隔 |
| 叠化 | `"上一幕画面缓慢叠化为: ..."` | 时间流逝 |
| 时间略过 | `"数小时之后, ..."` | 显式跳时间 |
| 空镜建场 | `"全景空镜, 介绍场景: ..."` + `model: wan2.7-t2v-2026-04-25` | 新场景第一镜 |

### Pacing — default to model maximum

**Hard rule: pick the largest legal duration.**

| Model | Max | Default |
|-------|-----|---------|
| `wan2.7-r2v` (no reference_video) | 15s | **15** |
| `wan2.7-i2v-2026-04-25` | 15s | **15** |
| `wan2.7-t2v-2026-04-25` | 15s | **15** |

Longer shots → fewer cuts → fewer identity drifts → lower cost.

When to drop below 15s:
1. Quick comedic punchline / reaction beat.
2. Pure transition bridge (3–5s establishing shot).
3. User explicitly asks for faster pacing.

### Model selection per shot

| Situation | Model | Why |
|-----------|-------|-----|
| Dialog / character interaction | `wan2.7-r2v` | reference_image + reference_voice |
| Establishing shot, no character | `wan2.7-t2v-2026-04-25` | No reference needed |
| Pure visual transition | `wan2.7-i2v-2026-04-25` | first_frame chaining enough |
| First shot of project | r2v or t2v | Must NOT need a previous frame |

**Mix target**: ~70% r2v + ~25% i2v + ~5% t2v.

### 续接黄金五条 — Continuity Rules

#### Rule 1 — 选对模型

See model selection table above. Don't make every shot r2v — transition
shots need i2v for smoother visual flow.

#### Rule 2 — 写连续的动作

Two prompts bracketing a cut must describe **one continuous action split
across the cut**, not two unrelated moments.

- ❌ "图1 站在柜台后, 双手叉腰" → "图1 转身走向门口"
- ✅ "图1 站在柜台后, 双手叉腰, **缓缓抬起右手指向门外**" → "**紧接前一镜头**, 图1 **缓缓放下右手, 转身**向门口走去"

#### Rule 3 — 锚词锁住延续性

Every chained shot must prepend:
- `"紧接前一镜头"`
- `"同样的服装与发型"` + any held prop
- One environment anchor word from scene description

#### Rule 4 — 复用 seed

Same scene → same seed for ALL shots. Scene change → seed change is fine.

#### Rule 5 — 续帧决策树

```
First shot of project?
├─ Yes → false
└─ No: different scene from previous?
     ├─ Yes → false (write a 硬切/渐隐/空镜 prefix)
     └─ No → true (chain via last_frame)
```

~1 in 4–6 shots will be `false`.

#### Rule 6 — 跨 shot 逻辑回溯 (Recall)

视频模型逐 shot 独立生成，没有记忆。

**同 scene 内**:
1. **背景角色 recall**: 切换视角时，1-2 个短语提到前一主角还在画面中。
2. **环境元素 recall**: 从 scene.description 挑 2-3 个锚定词重复使用。
3. **动作延续 recall**: shot N+1 用 "紧接前一镜头" + 描述 N 结尾姿态。

**跨 scene**: 不需要 visual recall，但叙事 recall 有时需要。

`scene.characters_present` 是你的 recall 清单。

### Prompt writing

For each shot prompt:

1. **Shot type**: 全景/中景/近景/特写 + 镜头运动 (推/拉/摇/跟).
2. **Character reference**: 图1/视频1 + display name from cast.json.
   Example: `"图1 佟掌柜 站在柜台后, 双手叉腰..."`
3. **Action + emotion + camera + light**: 1–2 sentences. Pull action verbs
   and mannerisms from soul cards. Pull relationships for chemistry.
4. **mood_anchor**: append verbatim from lore. Every. Single. Shot.
5. **Length**: 60–200 chars Chinese. Concrete physical detail.
6. **Respect constraints**: each character's `dont` + lore's `forbidden`.

### 台词必须嵌入 prompt

The video model has zero context. Dialog must be embedded directly in the
shot's prompt for r2v lip-sync.

1. Every user-supplied dialog line → verbatim in exactly one shot prompt.
2. Every script.md dialog line → in a shot prompt (unless deliberately cut).
3. Dialog shots MUST use `wan2.7-r2v`.
4. Max ~2 speaking characters per shot; 3+ → split into sequential shots.

### 主角不离场

1. Protagonist must appear in EVERY shot of their sequence (`characters[]`
   + described in `prompt`).
2. If protagonist is in cast.json → must use `wan2.7-r2v`.
3. Action sequences: describe BOTH attacker and target in EVERY shot.
4. Compress multiple hits into one longer shot rather than one-hit-per-shot.

### Negative prompt

Apply globally: `"低分辨率, 错误, 最差质量, 残缺, 多余的手指, 比例不良, 字幕水印"`

### Seeds & candidates

- `seed`: only when retrying deterministically.
- `candidates: 2-4` for hero shots (key emotional beats). Default `1` for
  filler shots.

### Output JSON shape

```json
{
  "project_id": "<id>",
  "title": "...",
  "synopsis": "...",
  "target_duration_s": 180,
  "resolution": "720P",
  "ratio": "16:9",
  "scenes": [ ... ],
  "shots": [ ... ]
}
```

Must match `src/videogen/storyboard.py` schema (`Scene` + `Shot` +
`Storyboard` Pydantic models).

## Failure recovery (during render)

When a shot returns `FAILED`:

1. Read the error in `shots_state.json`.
2. Common fixes:
   - **Content-policy block**: soften violence/IP terms, keep same `id`,
     run `render --shot <id> --force`.
   - **Reference image rejection**: recompress cast image, re-run `cast init`.
   - **Continuity drift**: switch i2v → r2v, add character to `characters[]`.
3. If 3× failure → degrade: r2v → i2v, or t2v if no continuity needed.

## DON'Ts

- ❌ Don't write the screenplay. The screenwriter does that.
- ❌ Don't invent character names not in `cast.json`.
- ❌ Don't use copyrighted IP names in prompts.
- ❌ Don't pick `duration < 15` without a reason.
- ❌ Don't set `duration > 10` on r2v shots with `reference_video`.
- ❌ Don't call `render` before `storyboard validate` passes.
- ❌ Don't call the Wan HTTP API directly — use the CLI.
