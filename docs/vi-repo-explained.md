# Giai thich repo spark-video

Tai lieu nay giai thich repo `spark-video` theo goc nhin: khi user go mot prompt tao video, AI Agent se doc file nao, suy luan ra sao, tao artifact nao, goi API nao, va cuoi cung ghep thanh `final.mp4` nhu the nao.

Repo nay khong phai mot app web hay mot CLI dong goi san. No la mot **agent skill + deterministic toolchain**:

- `SKILL.md`: entrypoint cho agent, dong vai tro producer/orchestrator.
- `references/spark-video-*/SKILL.md`: cac sub-skill, moi file la prompt/runbook cho mot vai tro sang tao.
- `scripts/*.py`: cac tool Python co tinh xac dinh, dung de scaffold, validate, render, review, stitch.
- `lib/*.py`: schema Pydantic, state helper, ffmpeg helper, BGM, render graph, review parser.
- `projects/<project>/episode-<NN>/`: runtime output, khong commit vao git.

## 1. Tech stack

Core:

- Python 3.10+.
- `uv run scripts/*.py` de chay script co inline dependencies.
- Pydantic v2 cho schema `Storyboard`, `Scene`, `Shot`, `BGMConfig`.
- ffmpeg/ffprobe de cat/ghep/mux audio, lay last frame, normalize/mix BGM.
- Bailian CLI `bl`, bat buoc goi qua wrapper `./scripts/bl` de log moi model call vao `logs/model_calls.jsonl`.
- DashScope/Aliyun video/image/TTS models thong qua `bl` hoac HTTP provider `dashscope_wan27.py`.

Model/provider:

- Provider mac dinh: `bl`.
- Concrete video model mac dinh theo kind:
  - `t2v` -> `happyhorse-1.0-t2v`.
  - `i2v` -> `happyhorse-1.0-i2v`.
  - `r2v` -> `happyhorse-1.0-r2v`.
- Provider fallback: `wan27`, dung `DASHSCOPE_API_KEY`/`BAILIAN_API_KEY` va HTTP API DashScope.
- Review model: `bl omni`, rubric 6 truc trong `references/spark-video-clip-review/rubric.md`.
- TTS narration: `./scripts/bl speech synthesize` hoac `scripts/tts_qwen.py` khi dung qwen-tts fallback.

## 2. Cac thanh phan chinh

### 2.1 Root producer

File: `SKILL.md`

Day la entrypoint khi user noi "Use spark-video...". Agent se doc file nay dau tien. File nay quy dinh:

- self-update skill bang `git pull --ff-only`.
- set env vars `SPARK_VIDEO_PROJECT`, `SPARK_VIDEO_EPISODE`, `SPARK_VIDEO_PHASE`.
- gate workflow 4+2:
  - GATE 0: chon mode `drama` hay `narration`.
  - GATE 0.5: BGM neu co thu muc `bgm/`.
  - GATE 1: duyet script.
  - GATE 2: duyet storyboard + estimate cost/time.
  - GATE 3: duyet rendered clips.
  - GATE 4: duyet final mp4.
- thu tu goi sub-skill va script.

### 2.2 Sub-skills

| File | Vai tro | Output chinh |
|---|---|---|
| `references/spark-video-screenwriter/SKILL.md` | Bien premise thanh screenplay theo tung scene | `scenes/scene-NN.md`, `scene-NN.ready` |
| `references/spark-video-director/SKILL.md` | Bien scene markdown thanh storyboard fragment | `scenes/scene-NN.json`, `direction.json` |
| `references/spark-video-cast/SKILL.md` | Tao asset nhan vat, boi canh, prop | `cast/`, `movie-set/`, `props/`, manifests |
| `references/spark-video-vfx-review/SKILL.md` | Optional pre-render static quality check | report truoc render |
| `references/spark-video-clip-review/SKILL.md` | Review/retry clip sau khi render | doc quy trinh rewrite/escalate |

### 2.3 Scripts

| File | Cong dung |
|---|---|
| `scripts/doctor.sh` | Kiem tra dependency: `bl`, `ffmpeg`, `uv`, Python, sub-skills |
| `scripts/scaffold.py` | Tao folder/template cho episode, lore, scene, cast, set, prop; rebuild manifests |
| `scripts/storyboard.py` | Compile `scene-*.md/json` thanh `script.md` va `storyboard.json`; validate, graph, estimate |
| `scripts/render_all.py` | Batch render, tinh chain groups, parallel across groups, sequential inside group |
| `scripts/render_shot.py` | Render mot shot, extract last frame, auto review, update `shots_state.json` |
| `scripts/stitch.py` | Lay winner clips, mux TTS neu narration, concat, mix BGM, tao final mp4 |
| `scripts/build_viewer.py` | Tao `viewer.html` hien thi premise, lore, script, scenes, assets, shots, reviews, final |
| `scripts/bl` | Wrapper quanh Bailian CLI, log tat ca model calls |
| `scripts/providers/bl.py` | Provider mac dinh goi `./scripts/bl video generate/ref` |
| `scripts/providers/dashscope_wan27.py` | Provider HTTP DashScope Wan 2.7 fallback |

### 2.4 Data models

File quan trong: `lib/storyboard.py`

`Storyboard` gom:

- `mode`: `drama` hoac `narration`.
- `provider`: `bl` hoac `wan27`.
- `ratio`: mac dinh `16:9`.
- `resolution`: mac dinh `720P`.
- `bgm`: optional `BGMConfig`.
- `scenes`: danh sach `Scene`.
- `shots`: danh sach `Shot`.

`Shot` co cac field quan trong:

- `id`: vi du `S01-001`.
- `kind`: `t2v`, `i2v`, `r2v`.
- `role`: `drama` hoac `narration`.
- `prompt`: prompt video.
- `duration`: 2-15 giay.
- `characters`: ten nhan vat match `cast.json`.
- `props`: ten prop match `props.json`.
- `set_id`: reference set.
- `use_prev_last_frame_as_first`: co noi tiep frame cuoi shot truoc khong.
- `narration_text`: chi hop le voi `role=narration`.
- `narrative_purpose`: ly do ton tai cua shot.

## 3. Cac mode

### 3.1 `drama`

Day la mode mac dinh cho short drama, video quang cao, phim ngan co hoi thoai.

Co che:

- Screenwriter viet scene co `Action` va `Dialog`.
- Director dua hoi thoai vao `Shot.prompt`.
- Video model tu tao hinh anh va audio/dialog trong tung clip.
- `stitch.py` chi concat va mix BGM; khong thay audio bang TTS.

Nen dung khi:

- Can nhan vat noi truc tiep trong canh.
- Can cam giac phim ngan, J-drama, quang cao, sitcom, suspense.

### 3.2 `narration`

Day la mode voiceover recap/pop-science/explainer.

Co che:

- Screenwriter viet scene thanh cac beat `Narration` va `Dialog`.
- Director map beat narration thanh shot ngan `role=narration`.
- Render video truoc.
- Den `stitch.py`, audio goc cua narration shot bi strip, TTS duoc synth tu `narration_text`, roi mux vao video.
- Dialog beat van co the la `role=drama`.

Nen dung khi:

- Pop-science/explainer.
- Recap style.
- Can voiceover on dinh hon viec de video model tu noi.

## 4. Cac lua chon quan trong

### 4.1 Provider

- `bl`: mac dinh, thong qua Bailian CLI wrapper.
- `wan27`: fallback, goi DashScope HTTP truc tiep, huu ich khi can first-frame bridging/negative_prompt/prompt_extend tot hon.

### 4.2 Shot kind

- `t2v`: text-to-video, khong co reference image. Tot cho establishing shot, abstract explainer visual.
- `i2v`: image-to-video, can mot first frame.
- `r2v`: reference-to-video, co cast/set/prop image references. Tot cho nhan vat, location, prop can consistent.

### 4.3 BGM

BGM khong gui vao video model. No la file local va duoc mix o buoc stitch.

Modes:

- `off`: khong mix BGM.
- `global`: mot track cho toan video.
- `scene`: director chon track theo scene, nhung trong code hien tai `stitch.py` moi implement common case global; scene-mode con TODO cho switching mid-video.

### 4.4 Aspect ratio/resolution

- `storyboard.json` co `ratio` mac dinh `16:9`, `resolution` mac dinh `720P`.
- `render_all.py --ratio 16:9` hoac `--ratio 9:16` co the override khi render.

### 4.5 Retry/review

- Threshold mac dinh: `7.0`.
- Max retry mac dinh: `3`.
- Moi clip duoc score 6 truc: `logic`, `proportion`, `physics`, `style`, `cast_match`, `dialog_attribution`.
- Bat ky truc nao <= veto floor mac dinh `5.0` se force reject.

## 5. Folder runtime output

Sau mot run, cau truc thuong la:

```text
projects/<project>/
├── initialPrompt.md
├── lore.md
├── bgm/
├── cast/
├── movie-set/
├── props/
└── episode-<NN>/
    ├── premise.md
    ├── bgm-config.json
    ├── direction.json
    ├── cast.json
    ├── movie_set.json
    ├── props.json
    ├── script.md
    ├── storyboard.json
    ├── shots_state.json
    ├── viewer.html
    ├── scenes/
    │   ├── scene-01.md
    │   ├── scene-01.ready
    │   └── scene-01.json
    ├── clips/
    │   ├── S01-001-ver1.mp4
    │   └── S01-001.mp4
    ├── frames/
    │   └── S01-001-ver1_last.png
    ├── reviews/
    │   └── S01-001-ver1.json
    ├── logs/
    │   └── model_calls.jsonl
    └── final/
        └── <project>-<NN>.mp4
```

`viewer.html` la dashboard doc moi thu: prompt ban dau, lore, script, storyboard, asset, tung clip attempt, review score, final video, va model call logs.

