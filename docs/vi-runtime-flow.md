# Luong xu ly tac vu trong spark-video

Tai lieu nay di theo thu tu thuc thi mot job tao video end-to-end.

## 1. Thu tu file agent doc

Voi cau lenh kieu:

```text
Use spark-video to generate ...
```

Agent skill-aware thuong doc theo thu tu:

1. `SKILL.md`
   - Xac dinh day la one-shot producer.
   - Doc gate workflow.
   - Xac dinh mode, provider, BGM, project/episode.
2. `scripts/doctor.sh`
   - Chay check dependency.
3. `scripts/scaffold.py`
   - Scaffold episode/lore/manifests.
4. `references/spark-video-cast/SKILL.md`
   - Neu can tao nhan vat/location/prop/reference images.
5. `references/spark-video-screenwriter/SKILL.md`
   - Quy tac viet `scene-NN.md`.
6. `references/spark-video-director/SKILL.md`
   - Quy tac viet `scene-NN.json` theo schema.
7. `lib/storyboard.py`
   - Schema ma director output phai match.
8. `scripts/storyboard.py`
   - Compile, validate, graph, estimate.
9. `scripts/render_all.py` va `scripts/render_shot.py`
   - Render va review.
10. `scripts/providers/bl.py` hoac `scripts/providers/dashscope_wan27.py`
    - Gui request toi model/API.
11. `lib/review.py` va `references/spark-video-clip-review/rubric.md`
    - Review clip.
12. `scripts/stitch.py`
    - Ghep final mp4.
13. `scripts/build_viewer.py`
    - Tao dashboard review.

Agent co the doc them:

- `projects/<project>/lore.md`.
- `projects/<project>/initialPrompt.md`.
- `projects/<project>/episode-<NN>/cast.json`.
- `movie_set.json`, `props.json`.
- `scenes/scene-NN.md/json`.
- `storyboard.json`, `shots_state.json`, `reviews/*.json`, `logs/model_calls.jsonl`.

## 2. Step 0: Preflight va scaffold

Agent set env:

```bash
export SPARK_VIDEO_PROJECT=<project_id>
export SPARK_VIDEO_EPISODE=<NN>
export SPARK_VIDEO_PHASE=producer
```

Sau do chay:

```bash
./scripts/doctor.sh
uv run scripts/scaffold.py episode --init
```

`scaffold.py episode --init` tao:

```text
projects/<p>/episode-<NN>/
├── scenes/
├── clips/
├── frames/
├── reviews/
├── logs/
├── final/
├── cast/
├── movie-set/
└── props/
```

Dong thoi tao project-tier folders:

```text
projects/<p>/
├── cast/
├── movie-set/
├── props/
└── bgm/
```

Agent phai persist prompt goc vao:

- `projects/<p>/initialPrompt.md`, hoac
- `projects/<p>/episode-<NN>/premise.md` neu la override rieng episode.

Day la audit trail va duoc `build_viewer.py` doc lai.

Neu `lore.md` chua co:

```bash
uv run scripts/scaffold.py lore --title "<title>"
```

Sau do agent can dien/suy luan noi dung `lore.md`, dac biet `mood_anchor`, vi director phai append mood anchor vao moi shot prompt.

## 3. Gate 0: chon mode

Neu user khong ghi ro, agent hoi:

- `drama`: short drama, hoi thoai/action nam trong video prompt.
- `narration`: voiceover/TTS recap/explainer.

Quyet dinh nay anh huong:

- Mau `scene-NN.md`.
- Field `Storyboard.mode`.
- Viec `stitch.py` co synth TTS/mux audio hay khong.

## 4. Gate 0.5: BGM

Agent kiem tra:

```text
projects/<p>/bgm/
projects/<p>/episode-<NN>/bgm/
```

Neu co file `.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg`, `.aac`, agent hoi:

- dung BGM khong?
- `global` hay `scene`?
- co forbid model-generated BGM khong?

Config duoc ghi vao:

```text
projects/<p>/episode-<NN>/bgm-config.json
```

`storyboard.py compile` doc file nay va dua vao `Storyboard.bgm`.

Luu y: render prompt trong `render_shot.py` hien tai luon append `"No background music."` neu prompt chua co cau do. BGM user cung cap duoc mix o `stitch.py`, khong gui len video model.

## 5. Asset/manifests: cast, set, prop

Agent chay:

```bash
uv run scripts/scaffold.py cast-init
uv run scripts/scaffold.py set-init
uv run scripts/scaffold.py prop-init
```

Output:

```text
projects/<p>/episode-<NN>/cast.json
projects/<p>/episode-<NN>/movie_set.json
projects/<p>/episode-<NN>/props.json
```

Neu prompt co nhan vat moi, location quan trong, prop lap lai, agent dung `spark-video-cast`:

- scaffold folder.
- tao reference image bang `./scripts/bl image generate` hoac `./scripts/bl image edit`.
- rebuild manifest.

Nguyen tac:

- Mot character folder = mot trang thai visual.
- Mot set folder = mot lighting/time-of-day state.
- Mot prop folder = mot narrative state.

## 6. Screenwriter: premise -> scene markdown

Agent/screenwriter doc:

1. `references/spark-video-screenwriter/SKILL.md`.
2. Shanyin screenwriting reference neu co.
3. `projects/<p>/lore.md`.
4. `projects/<p>/episode-<NN>/cast.json`.
5. Cac soul cards trong `cast/<name>/cast.md`.

Voi moi scene:

```bash
uv run scripts/scaffold.py scene --num <N> --mode <drama|narration>
```

Screenwriter ghi:

```text
projects/<p>/episode-<NN>/scenes/scene-NN.md
projects/<p>/episode-<NN>/scenes/scene-NN.ready
```

Trong mode `drama`, scene gom:

- Characters.
- Pacing.
- Estimated duration.
- Backstory.
- Action/Plot.
- Dialogue.

Trong mode `narration`, scene gom danh sach beat:

- `Narration`: text voiceover + visual.
- `Dialogue`: line nhan vat + visual.

Screenwriter khong duoc ghi `script.md` hay `storyboard.json` truc tiep.

## 7. Director: scene markdown -> scene JSON

Director doc:

1. `references/spark-video-director/SKILL.md`.
2. Shanyin director reference neu co.
3. `lore.md`.
4. `cast.json`.
5. `movie_set.json`.
6. `props.json`.
7. `scene-NN.md`.
8. `$SPARK_VIDEO_PROVIDER`.

Neu la scene 01 va chua co:

```text
projects/<p>/episode-<NN>/direction.json
```

Director tao `direction.json`.

Sau do ghi:

```text
projects/<p>/episode-<NN>/scenes/scene-NN.json
```

Moi fragment co shape:

```json
{
  "scene": {
    "id": "S01",
    "name": "...",
    "description": "...",
    "characters_present": [],
    "props_present": [],
    "set_id": null,
    "bgm_track": null,
    "seed": null
  },
  "shots": [
    {
      "id": "S01-001",
      "scene": "S01",
      "narrative_purpose": "...",
      "prompt": "...",
      "duration": 8,
      "kind": "r2v",
      "role": "drama",
      "characters": [],
      "props": [],
      "set_id": null,
      "use_prev_last_frame_as_first": false
    }
  ]
}
```

Sau moi scene:

```bash
uv run scripts/storyboard.py validate --scene <N>
```

## 8. Compile/validate/estimate/graph

Producer chay:

```bash
uv run scripts/storyboard.py compile --mode <drama|narration>
uv run scripts/storyboard.py validate
uv run scripts/storyboard.py graph
uv run scripts/storyboard.py estimate
```

`compile` lam hai viec:

- Merge `scenes/scene-*.md` -> `script.md`.
- Merge `scenes/scene-*.json` -> `storyboard.json`.

`validate` dung `Storyboard.model_validate` va lint:

- unknown character/prop/set.
- props gan vao `t2v/i2v`.
- dialog qua dai so voi duration.
- chain group mix nhieu set_id.
- time-of-day conflict.

`graph` goi `lib/render_graph.py`:

- Shot dau tien bat dau group moi.
- Bat ky shot co `use_prev_last_frame_as_first=false` bat dau group moi.
- Moi group render song song voi group khac.
- Trong group, shots render tuan tu vi shot sau can last frame shot truoc.

`estimate` tinh:

- tong so shots.
- tong clip seconds.
- duration by kind.
- so parallel groups.
- estimated render seconds.
- thong tin TTS neu `mode=narration`.

## 9. Gate 1 va Gate 2

Sau compile:

```bash
uv run scripts/build_viewer.py
```

GATE 1:

- User xem `script.md`.
- Neu sua, agent sua `scene-NN.md`, compile lai.

GATE 2:

- User xem `storyboard.json`, shot list, estimate.
- Neu sua, agent route feedback cho director, sua `scene-NN.json`, validate/compile lai.

Neu `--vfx`, chay VFX review truoc render.

## 10. Render all shots

Producer khong nen goi `render_shot.py` tung shot bang tay. Dung:

```bash
uv run scripts/render_all.py --reset --ratio 16:9
```

`render_all.py` lam:

1. Doc `storyboard.json`.
2. Doc `shots_state.json` neu co.
3. Build indexes:
   - character -> image path tu `cast.json` hoac folder fallback.
   - set -> image path tu `movie_set.json`.
   - prop -> image path tu `props.json`.
4. Compute chain groups bang `compute_chain_groups`.
5. Chay `ProcessPoolExecutor` theo group.
6. Moi group goi `_render_chain_group` tuan tu:
   - resolve media: cast portraits -> set image -> prop images.
   - build command `uv run scripts/render_shot.py ...`.
   - neu shot can chain, truyen `--first-frame <prev_last_frame>`.
7. Doc lai `shots_state.json` lam ground truth va in summary JSON.

## 11. Render mot shot

`scripts/render_shot.py` thuc hien atomic render-review-promote.

Input tu `render_all.py`:

- `--shot`.
- `--kind`.
- `--prompt`.
- `--duration`.
- `--media`.
- optional `--ratio`, `--provider`, `--seed`, `--negative-prompt`, `--characters`, `--first-frame`.

Thu tu:

1. Xac dinh episode dir.
2. Doc `shots_state.json`.
3. Tinh next version.
4. Chon provider:
   - env/arg `bl` -> `scripts.providers.bl`.
   - `wan27` -> `scripts.providers.dashscope_wan27`.
5. Resolve media/voice paths absolute.
6. Append `"No background music."` vao prompt neu chua co.
7. Goi `provider.render(...)`.
8. Ghi clip:
   - `clips/<shot>-ver<N>.mp4`.
9. Extract last frame bang ffmpeg:
   - `frames/<shot>-ver<N>_last.png`.
10. Ghi attempt vao `shots_state.json` bang file lock.
11. Auto review bang `lib.review.score_clip`.
12. Ghi review sidecar:
   - `reviews/<shot>-ver<N>.json`.
13. Neu `ACCEPT`, copy winner:
   - `clips/<shot>.mp4`.
14. Embed review vao `shots_state.json`.
15. Rebuild `viewer.html --no-open`.

## 12. Provider `bl`: gui du lieu qua Bailian CLI

File: `scripts/providers/bl.py`

Mapping:

- `kind=t2v`:

```bash
./scripts/bl --output json video generate \
  --prompt "<prompt>" \
  --duration <duration> \
  --download <clips/shot-verN.mp4>
```

- `kind=i2v`:

```bash
./scripts/bl --output json video generate \
  --prompt "<prompt>" \
  --image <first-frame-or-image> \
  --duration <duration> \
  --download <out>
```

- `kind=r2v`:

```bash
./scripts/bl --output json video ref \
  --prompt "<prompt>" \
  --duration <duration> \
  --image <cast portrait> \
  --image <set image> \
  --image <prop image> \
  --image-voice <voice.mp3 optional> \
  --download <out>
```

Provider retry toi da 3 lan cho loi transient network/socket.

Tat ca call qua `./scripts/bl` nen duoc log vao:

```text
projects/<p>/episode-<NN>/logs/model_calls.jsonl
```

## 13. Provider `wan27`: gui truc tiep DashScope HTTP

File: `scripts/providers/dashscope_wan27.py`

Thu tu:

1. Upload local media qua:

```bash
./scripts/bl --output json file upload --file <path> --model <model>
```

2. Submit async task toi:

```text
POST https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis
```

3. Poll:

```text
GET https://dashscope.aliyuncs.com/api/v1/tasks/<task_id>
```

4. Download `video_url` ve `clips/<shot>-ver<N>.mp4`.

Model map:

- `t2v`: `wan2.7-t2v-2026-04-25`.
- `i2v`: `wan2.7-i2v-2026-04-25`.
- `r2v`: `wan2.7-r2v`.

## 14. Review/retry

`lib/review.py` build call:

```bash
./scripts/bl omni \
  --system "$(cat references/spark-video-clip-review/rubric.md)" \
  --message "<shot id, prompt, expected characters, threshold>" \
  --video <clips/S01-001-ver1.mp4> \
  --image <cast portrait 1> \
  --image <cast portrait 2> \
  --text-only \
  --output json
```

Review output duoc parse thanh:

```json
{
  "score": 8.1,
  "breakdown": {
    "logic": 8,
    "proportion": 8,
    "physics": 8,
    "style": 9,
    "cast_match": 8,
    "dialog_attribution": 8
  },
  "verdict": "ACCEPT",
  "critique": "...",
  "vetoed_axes": null
}
```

Neu `REJECT`, `render_all.py` chi bao summary. Agent doc `critique`, sua prompt trong `scenes/scene-NN.json`, compile lai, roi:

```bash
uv run scripts/render_all.py --rejected-only
```

Neu qua retry ma van fail:

- chon best-of-N bang `render_shot.py --accept-version <N>` hoac
- tao escalation cho director sua cau truc shot.

## 15. Gate 3

Khi moi shot co `winner_version`, agent build viewer:

```bash
uv run scripts/build_viewer.py
```

User xem:

- moi shot.
- moi version.
- winner.
- review score/critique.

Neu user yeu cau rerender shot nao:

```bash
uv run scripts/render_all.py --shot S01-002
```

## 16. Stitch final

Chay:

```bash
uv run scripts/stitch.py --crossfade 0.5
```

`stitch.py`:

1. Doc `storyboard.json`.
2. Doc `shots_state.json`.
3. Theo thu tu `Storyboard.shots`, lay `clips/<shot>.mp4`.
4. Neu co continuation `clips/<shot>b.mp4` thi xfade join.
5. Neu `mode=narration` va shot `role=narration`:
   - synth TTS tu `shot.narration_text`.
   - fit TTS voi video duration bang `atempo` neu can.
   - strip audio goc va mux TTS vao clip.
6. Concat tat ca clips.
7. Neu `Storyboard.bgm.enabled` va `mode=global`:
   - resolve track tu `projects/<p>/bgm` hoac episode `bgm`.
   - mix BGM bang ffmpeg, co fade in/out.
8. Copy vao:

```text
projects/<p>/episode-<NN>/final/<project>-<NN>.mp4
```

9. Build `viewer.html`.

## 17. Gate 4

User xem final trong `viewer.html`.

Neu can sua:

- Shot loi hinh: quay lai Gate 3, render shot do.
- Script/storyboard sai: quay lai Gate 1/2 va re-render affected shots.
- BGM loud/quiet: sua `storyboard.bgm.volume` hoac `bgm-config.json`, chay lai `stitch.py`.

