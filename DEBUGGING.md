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

Hand-craft `projects/smoke/storyboard.json` with **2 shots only**:

```json
{
  "project_id": "smoke",
  "title": "smoke test",
  "synopsis": "two shots to verify the pipeline.",
  "target_duration_s": 16,
  "resolution": "720P",
  "ratio": "16:9",
  "shots": [
    {
      "id": "S01-001",
      "scene": "S01",
      "duration": 5,
      "prompt": "全景, 慢推. 图1站在客栈柜台后, 双手叉腰, 表情得意. 明朝架空, 喜剧光线, 暖色调.",
      "characters": ["佟掌柜"],
      "model": "wan2.7-r2v",
      "use_prev_last_frame_as_first": false
    },
    {
      "id": "S01-002",
      "scene": "S01",
      "duration": 5,
      "prompt": "中景, 平移. 图1转身走向门口, 长袍随风扬起. 明朝架空, 喜剧光线, 暖色调.",
      "characters": ["佟掌柜"],
      "model": "wan2.7-r2v"
    }
  ]
}
```

Then:

```bash
videogen storyboard validate --project smoke
videogen storyboard show --project smoke
```

Catches all schema/cast-mismatch issues before any render.

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
