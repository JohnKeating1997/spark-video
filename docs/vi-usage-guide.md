# Huong dan su dung spark-video

## 1. Kiem tra moi truong

Trong repo:

```bash
cd D:/OneDrive/livetobuild/workflowshortdrama/spark-video
./scripts/doctor.sh
```

Can co:

- `uv`.
- `ffmpeg`.
- `bl` CLI da login.
- API key neu dung `wan27`: `DASHSCOPE_API_KEY` hoac `BAILIAN_API_KEY`.

Tat ca lenh model phai di qua:

```bash
./scripts/bl
```

Khong goi raw `bl`, vi wrapper nay ghi audit log.

## 2. Cach goi trong agent

Prompt toi thieu:

```text
Use spark-video to make a 2-minute J-drama first-love short. Project: jdrama-first-love, episode 001. 16:9. Premise: ...
```

Prompt co mode:

```text
Use spark-video with --mode=narration to make a pop-science explainer under 3 minutes. Project: muscle-popscience, episode 001. Premise: ...
```

Neu khong dua `project`/`episode`, agent phai tu dat hoac hoi lai. Nen dua ro de output de quan ly.

## 3. Chay thu cong cac buoc chinh

### 3.1 Set env

PowerShell:

```powershell
$env:SPARK_VIDEO_PROJECT="demo"
$env:SPARK_VIDEO_EPISODE="001"
$env:SPARK_VIDEO_PROVIDER="bl"
```

Bash:

```bash
export SPARK_VIDEO_PROJECT=demo
export SPARK_VIDEO_EPISODE=001
export SPARK_VIDEO_PROVIDER=bl
```

### 3.2 Scaffold

```bash
uv run scripts/scaffold.py episode --init
uv run scripts/scaffold.py lore --title "Demo"
uv run scripts/scaffold.py manifests
```

Dien `projects/demo/lore.md`, dac biet `mood_anchor`.

### 3.3 Them BGM

Dat file audio vao:

```text
projects/demo/bgm/
```

hoac:

```text
projects/demo/episode-001/bgm/
```

Tao `bgm-config.json`:

```json
{
  "enabled": true,
  "mode": "global",
  "forbid_model_bgm": true,
  "track": "your-file-stem",
  "volume": 0.25,
  "fade_in_s": 0.5,
  "fade_out_s": 1.0
}
```

### 3.4 Tao scene/script

Agent thuong lam buoc nay. Neu thu cong:

```bash
uv run scripts/scaffold.py scene --num 1 --mode drama
```

Sua:

```text
projects/demo/episode-001/scenes/scene-01.md
```

Sau khi xong:

```bash
touch projects/demo/episode-001/scenes/scene-01.ready
```

PowerShell tuong duong:

```powershell
New-Item -ItemType File -Force projects/demo/episode-001/scenes/scene-01.ready
```

### 3.5 Tao storyboard fragment

Agent/director viet:

```text
projects/demo/episode-001/scenes/scene-01.json
```

Validate:

```bash
uv run scripts/storyboard.py validate --scene 1
```

### 3.6 Compile

```bash
uv run scripts/storyboard.py compile --mode drama
uv run scripts/storyboard.py validate
uv run scripts/storyboard.py graph
uv run scripts/storyboard.py estimate
uv run scripts/build_viewer.py --no-open
```

Doc:

```text
projects/demo/episode-001/viewer.html
```

### 3.7 Render

Full render:

```bash
uv run scripts/render_all.py --reset --ratio 16:9
```

Render shot cu the:

```bash
uv run scripts/render_all.py --shot S01-002
```

Render failed/rejected only:

```bash
uv run scripts/render_all.py --failed-only
uv run scripts/render_all.py --rejected-only
```

### 3.8 Stitch

```bash
uv run scripts/stitch.py --crossfade 0.5
```

Final:

```text
projects/demo/episode-001/final/demo-001.mp4
```

## 4. Dieu chinh chat luong

### 4.1 Sua script

Sua:

```text
scenes/scene-NN.md
```

Roi:

```bash
uv run scripts/storyboard.py compile --mode <mode>
uv run scripts/storyboard.py validate
```

Neu da render roi, can re-render cac shots bi anh huong.

### 4.2 Sua storyboard/prompt

Sua:

```text
scenes/scene-NN.json
```

Roi:

```bash
uv run scripts/storyboard.py compile --mode <mode>
uv run scripts/storyboard.py validate
uv run scripts/render_all.py --shot <SHOT_ID>
```

### 4.3 Accept mot version cu

Neu viewer cho thay version 2 tot hon winner:

```bash
uv run scripts/render_shot.py --shot S03-002 --accept-version 2
uv run scripts/stitch.py --crossfade 0.5
```

### 4.4 Tang/giam review strictness

```bash
export SPARK_VIDEO_REVIEW_THRESHOLD=7.5
export SPARK_VIDEO_REVIEW_VETO_FLOOR=5.0
export SPARK_VIDEO_MAX_RETRY=3
```

Khong nen tat review tru khi user chap nhan rui ro:

```bash
export VIDEOGEN_REVIEW_MODEL=""
```

## 5. Cac env vars hay dung

| Var | Mac dinh | Y nghia |
|---|---|---|
| `SPARK_VIDEO_PROJECT` | required | project id |
| `SPARK_VIDEO_EPISODE` | required | episode id, vi du `001` |
| `SPARK_VIDEO_PROVIDER` | `bl` | `bl` hoac `wan27` |
| `SPARK_VIDEO_MAX_CONCURRENCY` | `4` | so chain groups render song song |
| `SPARK_VIDEO_REVIEW_THRESHOLD` | `7.0` | nguong ACCEPT |
| `SPARK_VIDEO_MAX_RETRY` | `3` | so retry moi shot |
| `SPARK_VIDEO_RENDER_TIMEOUT_S` | `900` | timeout render |
| `SPARK_VIDEO_NARRATOR_VOICE` | `longanyang` | voice narration |
| `SPARK_VIDEO_NARRATOR_SPEECH_RATE` | `1.2` | toc do TTS |
| `VIDEOGEN_PROJECTS_DIR` | `./projects` | root output |

## 6. Loi thuong gap

### Agent khong nhan spark-video

Mo session moi sau khi install skill.

### `bl: command not found`

Cai Bailian CLI va login:

```bash
npm install -g bailian-cli
bl auth login
```

### Render khong co clip winner

Doc:

```text
projects/<p>/episode-<NN>/shots_state.json
projects/<p>/episode-<NN>/reviews/
projects/<p>/episode-<NN>/logs/model_calls.jsonl
```

Sau do:

```bash
uv run scripts/render_all.py --failed-only
```

### Face/character drift

Kiem tra:

- Shot co `kind=r2v` khong.
- `characters` co dung ten trong `cast.json` khong.
- Portrait co ton tai khong.
- Prompt co dang mo ta lai quan ao/toc/mat va mau thuan voi portrait khong.

### Set/location bi flicker

Kiem tra:

- Chain group co mix `set_id` ngay/dem khong.
- Neu doi lighting/time/location, set `use_prev_last_frame_as_first=false`.
- Tao set folder rieng cho tung lighting state.

### BGM khong vao final

Kiem tra:

- File audio nam trong `projects/<p>/bgm` hoac `projects/<p>/episode-<NN>/bgm`.
- `bgm-config.json` co `enabled: true`, `mode: "global"`, `track` dung filename stem.
- `storyboard.py compile` da chay sau khi tao `bgm-config.json`.

## 7. Nen doc file nao tiep?

Doc theo thu tu:

1. `docs/vi-repo-explained.md` de nam thanh phan.
2. `docs/vi-runtime-flow.md` de nam luong end-to-end.
3. `docs/vi-example-prompts.md` de hieu hai prompt mau.
4. `SKILL.md` neu muon xem runbook goc cho agent.
5. `references/spark-video-*/SKILL.md` neu muon sua cach agent suy luan.
