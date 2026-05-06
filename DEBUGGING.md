# Debugging guide

A 35-shot render takes 60–90 minutes; you don't want to find bugs at minute 80.
Use this ladder, lowest-cost first.

## Tier 0 — Static checks (free)

```bash
videogen doctor
```

Verifies env + ffmpeg + region. **Always run this first** in a new shell.

## Tier 1 — Cast wiring (1 API call total)

```bash
# Dry run, no upload — confirms ./cast pairing is right.
videogen cast init --project smoke --no-upload

# Real upload — costs nothing on Wan but exercises DashScope OSS.
videogen cast init --project smoke
cat projects/smoke/cast.json
```

If a character has no voice you'll see `"audio_local": null`. That's OK if you
don't need them to speak.

## Tier 2 — Storyboard schema (free)

Hand-craft `projects/smoke/storyboard.json` with **2 shots only**.

> **重要：连续两段必须写成"一个连贯动作的两半"**，不是两个独立动作。
> r2v 模型只把 `first_frame` 当软参考，所以续接靠的是 prompt 锚词 + 同 seed
> 同步运镜，不是只靠传末帧。详细规则见
> `.claude/skills/video-director/SKILL.md` 的"续接黄金五条"。

```json
{
  "project_id": "smoke",
  "title": "smoke test",
  "synopsis": "two shots forming one continuous action — verifies pipeline AND continuity.",
  "target_duration_s": 30,
  "resolution": "720P",
  "ratio": "16:9",
  "shots": [
    {
      "id": "S01-001",
      "scene": "S01",
      "duration": 15,
      "prompt": "全景, 镜头缓慢推进. 图1 站在当铺柜台后, 双手叉腰, 表情得意, 缓缓抬起右手食指指向门外. 木质柜台、暖黄烛光、明朝架空风格, 喜剧光线.",
      "characters": ["钱夫人"],
      "model": "wan2.7-r2v",
      "use_prev_last_frame_as_first": false,
      "seed": 12345
    },
    {
      "id": "S01-002",
      "scene": "S01",
      "duration": 15,
      "prompt": "中景, 紧接前一镜头, 镜头跟随. 图1 同样的服装与发型, 缓缓放下右手, 转身向门口走去, 长袍随步伐轻轻飘起. 木质柜台、暖黄烛光、明朝架空风格, 喜剧光线.",
      "characters": ["钱夫人"],
      "model": "wan2.7-r2v",
      "seed": 12345
    }
  ]
}
```

三个让它"真的连起来"的关键，新手最容易漏：

1. **第一段以"前置动作"收尾**（"抬手指向门外"）→ 第二段就有动机自然衔接（"放下手转身"），而不是凭空切到新动作。
2. **第二段开头加"紧接前一镜头""同样的服装与发型"等锚词**，把人物和场景的延续性写死。
3. **两段同 seed**（如 `12345`），明显降低光照、构图、服装褶皱漂移。

然后：

```bash
videogen storyboard validate --project smoke
videogen storyboard show --project smoke
```

Catches all schema/cast-mismatch issues before any render.

### 替代示例：纯运镜续接（i2v）

如果你想测的是"画面无缝接续"（不要任何对白），把 S01-002 换成 i2v 模型，
它对 `first_frame` 的尊重度比 r2v 高很多：

```json
{
  "id": "S01-002",
  "scene": "S01",
  "duration": 5,
  "prompt": "镜头紧接前一画面, 缓缓向左横摇, 揭示当铺门外的街景. 暖黄烛光, 明朝架空, 喜剧光线.",
  "characters": [],
  "model": "wan2.7-i2v-2026-04-25",
  "seed": 12345
}
```

代价：i2v 不读 reference_voice，所以这段不能让角色说话。**适合纯转场/运镜段**。

## Tier 2.5 — Budget gate (free)

Before any real render, check the budget:

```bash
videogen storyboard estimate --project smoke
echo "exit code: $?"
```

Expected output: 一张表打印 `shots / total duration / wall-clock estimate /
duration by model / verdict`. Exit code is **0** if total ≤
`VIDEOGEN_LONG_CONFIRM_S` (default 180s), **2** if over.

This is the same call the agent uses to decide whether to ask the user for
explicit approval, so test it once with a long storyboard to make sure your
threshold is what you want:

```bash
# Temporarily lower the threshold to verify the gate fires.
VIDEOGEN_LONG_CONFIRM_S=10 videogen storyboard estimate --project smoke
# → exit 2, "OVER BUDGET" in the verdict row
```

For machine-readable output (what the agent reads in tool-loop mode):

```bash
videogen storyboard estimate --project smoke --json
```

## Tier 3 — Single-shot render (1–3 min)

```bash
videogen render --project smoke --shot S01-001 --force
```

This is your fastest end-to-end signal. Inspect:

- `projects/smoke/clips/S01-001.mp4` — the actual output
- `projects/smoke/frames/S01-001_last.png` — last frame for chaining
- `projects/smoke/shots_state.json` — task_id, video_url, paths

If it fails, copy the `task_id` and run `videogen task query <id>` to get the
full DashScope error.

## Tier 4 — Two-shot continuity check

```bash
videogen render --project smoke
```

The second shot uses shot 1's last frame. Open both clips side by side; the
first frame of `S01-002.mp4` should match the last frame of `S01-001.mp4`.

If you see a hard cut between them:
- Confirm `use_prev_last_frame_as_first: true` (default).
- Check `shots_state.json` for `last_frame_url` — must be a valid `oss://` URL.

## Tier 5 — Stitch sanity

```bash
videogen stitch --project smoke
ffprobe -v error -show_entries format=duration projects/smoke/final/smoke.mp4
```

Final duration should equal the sum of shot durations (within 0.1s).

## Common failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `No API-key provided` | DASHSCOPE_API_KEY missing | edit `.env` |
| `current user api does not support synchronous calls` | header missing | shouldn't happen — file a bug, check `wan.py` |
| `task_status: FAILED` with content message | content policy on prompt or reference | rewrite prompt; for cast images, swap to a less ambiguous portrait |
| Character looks different between shots | model degraded to t2v/i2v | force `wan2.7-r2v` and add the character to `characters: [...]` |
| ffmpeg concat: "Invalid data" | one of the clips is 0 bytes | re-render that shot with `--force` |
| 30-min stuck on PENDING | Wan queue backed up | normal during peak hours; CLI auto-waits up to 30 min |

## Logs

`subprocess.run(..., capture_output=True)` swallows ffmpeg output. If a stitch
fails, run the printed `ffmpeg ...` command manually with stderr showing.

## Telemetry to pre-instrument later (TODO)

- Per-shot wall-clock + first-attempt vs retry success rate
- Cost per project (sum of `output_video_duration` × resolution multiplier)
- Per-character "cast quality" score (how often the model nails identity)
