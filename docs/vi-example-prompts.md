# Mapping hai prompt mau vao pipeline

Tai lieu nay giai thich voi hai prompt cu the, agent co kha nang chon mode nao, tao artifact nao, va goi model/API nao.

## Prompt A: Pop-science muscle explainer

User prompt:

```text
Use spark-video to generate an entertaining pop-science video, under 3 minutes, explaining from a scientific angle why humans — compared to other mammals — have such a hard time maintaining strong muscles. Use ~/Documents/darktown-strutters-ball.mp3 as the background music.
```

### 1. Suy luan ban dau

Agent nen suy luan:

- The loai: pop-science/explainer.
- Muc tieu: duoi 3 phut, giai thich khoa hoc nhung entertaining.
- BGM: user chi dinh local file `~/Documents/darktown-strutters-ball.mp3`.
- Format khong noi aspect ratio, nen mac dinh `16:9` neu khong hoi lai.
- Mode phu hop: `narration`, vi explainer/pop-science nen voiceover on dinh hon drama.

Neu agent tuan thu gate nghiem ngat, van hoi GATE 0. Neu user khong tra loi, default co the la `drama` theo docs, nhung ve logic san pham prompt nay phu hop `narration` hon. Nen khi viet run, nen pass flag `--mode=narration` hoac tra loi Gate 0 la narration.

### 2. Project setup de xuat

Vi user khong neu project/episode, agent can dat mot id hop ly, vi du:

```bash
export SPARK_VIDEO_PROJECT=muscle-popscience
export SPARK_VIDEO_EPISODE=001
export SPARK_VIDEO_PHASE=producer
```

Sau do:

```bash
./scripts/doctor.sh
uv run scripts/scaffold.py episode --init
```

Ghi prompt goc vao:

```text
projects/muscle-popscience/initialPrompt.md
```

Copy hoac reference BGM vao thu muc project:

```text
projects/muscle-popscience/bgm/darktown-strutters-ball.mp3
```

Repo khong co lenh copy BGM rieng; agent thuc te se copy file local bang shell hoac yeu cau user dat file vao `bgm/`. Sau do ghi:

```json
{
  "enabled": true,
  "mode": "global",
  "forbid_model_bgm": true,
  "track": "darktown-strutters-ball",
  "volume": 0.25,
  "fade_in_s": 0.5,
  "fade_out_s": 1.0
}
```

vao:

```text
projects/muscle-popscience/episode-001/bgm-config.json
```

### 3. Lore

Agent scaffold/dien:

```text
projects/muscle-popscience/lore.md
```

Noi dung nen co:

- `duration_target_s: 170` hoac nho hon 180.
- `genre: pop-science explainer`.
- `mood_anchor`: vi du `bright classroom lab, playful infographics, warm documentary lighting`.
- `forbidden`: misinformation, scary medical imagery, gore.

### 4. Cast/set/prop

Prompt nay khong bat buoc nhan vat consistent. Tuy nhien agent co the tao:

- Mot narrator/host neu video co host hien hinh.
- Cac set explainer:
  - `science-studio-warm`.
  - `gym-lab-demo`.
- Cac prop/reference neu can:
  - muscle fiber diagram khong nhat thiet la prop; neu chi la t2v visual thi khong can.

Voi narration mode, nhieu shots co the la `t2v`, khong can cast image. Neu co host, dung `r2v` cho shots host.

### 5. Screenwriter output

Screenwriter tao 4-6 scenes, vi target duoi 180s:

```text
projects/muscle-popscience/episode-001/scenes/
├── scene-01.md
├── scene-01.ready
├── scene-02.md
├── scene-02.ready
...
```

Noi dung mode narration co the chia beat:

- Hook: tai sao con nguoi "yeu" hon gorilla/horse ve duy tri muscle.
- Evolution tradeoff: endurance, brain energy, walking economy.
- Muscle protein turnover: use-it-or-lose-it.
- Hormones and aging.
- Modern lifestyle.
- Practical close: resistance training, protein, sleep.

Moi narration line nen ngan de TTS khop hinh.

### 6. Director output

Director tao:

```text
projects/muscle-popscience/episode-001/direction.json
projects/muscle-popscience/episode-001/scenes/scene-01.json
...
```

Shot style:

- Nhieu `t2v` visual metaphor/infographic.
- `role=narration` cho voiceover.
- `duration` 3-6s moi narration shot.
- `use_prev_last_frame_as_first=false` de parallel render.
- Co the co vai `r2v` neu host/cast can consistent.

Vi narration shot khong can chain, graph se co nhieu group, render nhanh hon.

### 7. API calls khi render

Voi mot `t2v` narration shot:

```bash
uv run scripts/render_shot.py \
  --shot S01-001 \
  --kind t2v \
  --prompt "<bright science visual... No background music.>" \
  --duration 4 \
  --ratio 16:9
```

Provider `bl.py` goi:

```bash
./scripts/bl --output json video generate \
  --prompt "<prompt>" \
  --duration 4 \
  --download projects/muscle-popscience/episode-001/clips/S01-001-ver1.mp4
```

Neu co host `r2v`:

```bash
./scripts/bl --output json video ref \
  --prompt "<host explains...>" \
  --duration 8 \
  --image projects/muscle-popscience/episode-001/cast/Host/portrait1.png \
  --image projects/muscle-popscience/movie-set/science-studio-warm/set1.png \
  --download ...
```

Moi render xong:

- `frames/Sxx-xxx-verN_last.png`.
- `reviews/Sxx-xxx-verN.json`.
- `shots_state.json` updated.

Review `bl omni` co the khong can cast image voi t2v, nhung van score logic/style/physics/proportion/dialog attribution.

### 8. Stitch voi TTS va BGM

Trong `stitch.py`:

- Moi `role=narration` synth TTS tu `narration_text`.
- Audio goc clip bi thay bang TTS.
- Tat ca clips concat theo thu tu storyboard.
- `darktown-strutters-ball.mp3` duoc resolve tu BGM folder va mix global.
- Output:

```text
projects/muscle-popscience/episode-001/final/muscle-popscience-001.mp4
```

## Prompt B: J-drama first love

User prompt:

```text
J-drama style. A high-school girl's sweet, awkward first-love story — heartwarming enough to make the viewer want to fall in love. About 2 minutes long. 16:9.
```

### 1. Suy luan ban dau

Agent nen suy luan:

- The loai: short drama / romantic J-drama.
- Target: khoang 2 phut, `16:9`.
- Mode phu hop: `drama`.
- BGM: user khong chi dinh, nen khong mix BGM tru khi co file trong `bgm/` va user chon.
- Can cast consistency cao: nu sinh, love interest, ban than/teacher neu co.
- Can set consistency: classroom, corridor, train station/school gate.

### 2. Project setup de xuat

```bash
export SPARK_VIDEO_PROJECT=jdrama-first-love
export SPARK_VIDEO_EPISODE=001
export SPARK_VIDEO_PHASE=producer
./scripts/doctor.sh
uv run scripts/scaffold.py episode --init
```

Ghi prompt:

```text
projects/jdrama-first-love/initialPrompt.md
```

### 3. Lore

`projects/jdrama-first-love/lore.md` nen co:

- `duration_target_s: 120`.
- `genre: J-drama first love`.
- `mood_anchor`: vi du `soft spring daylight, gentle handheld realism, pastel school romance, warm emotional closeups`.
- `forbidden`: explicit sexual content, adult/minor framing, bullying cruelty, melodrama gore.

### 4. Cast/set assets

Agent dung `spark-video-cast` tao:

```text
projects/jdrama-first-love/cast/
├── Aoi/
│   ├── cast.md
│   └── portrait1.png
├── Ren/
│   ├── cast.md
│   └── portrait1.png
└── BestFriend/
```

Set:

```text
projects/jdrama-first-love/movie-set/
├── classroom-spring-day/
│   ├── set.md
│   └── set1.png
├── school-corridor-golden-hour/
├── school-gate-after-rain/
└── train-platform-evening/
```

Prop neu recurring:

```text
projects/jdrama-first-love/props/
├── folded-note-intact/
└── umbrella-blue/
```

Sau moi asset:

```bash
uv run scripts/scaffold.py manifests
```

### 5. Screenwriter output

Voi 120s, screenwriter nen tao 3-4 scenes:

1. Classroom: awkward first glance.
2. Corridor/gate: accidental umbrella/note moment.
3. Train platform or school rooftop: almost-confession.
4. Closing beat: small smile, mutual feeling.

Output:

```text
projects/jdrama-first-love/episode-001/scenes/scene-01.md
projects/jdrama-first-love/episode-001/scenes/scene-01.ready
...
```

Mode `drama` nen co dialogue ngan, de video model co co hoi tao speech.

### 6. Director output

Director tao shot `r2v` la chinh:

- closeup Aoi nervous smile.
- medium two-shot Ren and Aoi.
- insert prop note/umbrella.
- establishing t2v school exterior co the dung `t2v`.

Vi can nhan vat consistent, nhieu shot dung:

```json
"kind": "r2v",
"characters": ["Aoi", "Ren"],
"set_id": "classroom-spring-day",
"props": ["folded-note-intact"]
```

Director phai:

- Khong mo ta dong phuc/toc/mat trong prompt neu da co portrait.
- Nhac age/young student style theo quy tac an toan va consistency.
- Append `mood_anchor` vao moi prompt.
- `use_prev_last_frame_as_first=true` chi khi shot sau noi tiep hanh dong shot truoc.
- Break chain giua location/time khac de render song song va tranh lighting flicker.

### 7. API calls khi render

Voi `r2v` classroom shot:

```bash
uv run scripts/render_shot.py \
  --shot S01-002 \
  --kind r2v \
  --prompt "<medium closeup [Image 1] Aoi reacts... dialogue... mood_anchor. No background music.>" \
  --duration 12 \
  --media \
    projects/jdrama-first-love/cast/Aoi/portrait1.png \
    projects/jdrama-first-love/cast/Ren/portrait1.png \
    projects/jdrama-first-love/movie-set/classroom-spring-day/set1.png \
    projects/jdrama-first-love/props/folded-note-intact/prop1.png \
  --characters Aoi Ren \
  --ratio 16:9
```

Provider `bl.py` goi:

```bash
./scripts/bl --output json video ref \
  --prompt "<prompt>" \
  --duration 12 \
  --image <Aoi portrait> \
  --image <Ren portrait> \
  --image <classroom set> \
  --image <note prop> \
  --download clips/S01-002-ver1.mp4
```

Review `lib/review.py` goi `bl omni` kem portraits Aoi/Ren de score `cast_match`.

Neu reject vi face drift/dialog attribution:

- Agent doc `reviews/S01-002-ver1.json`.
- Sua prompt trong `scene-01.json`.
- Compile lai.
- Render lai `--rejected-only` hoac `--shot S01-002`.

### 8. Stitch

Mode `drama`:

- Khong synth TTS cho shot drama.
- Audio cua video model duoc giu lai.
- Neu co BGM global thi mix o final, con neu khong co thi chi concat/crossfade.

Output:

```text
projects/jdrama-first-love/episode-001/final/jdrama-first-love-001.mp4
```

## Khac biet quan trong giua hai prompt

| Dimension | Pop-science | J-drama |
|---|---|---|
| Mode nen chon | `narration` | `drama` |
| Audio chinh | TTS narration o stitch | Video model tao dialogue/audio |
| Shot kind | Nhieu `t2v`, mot it `r2v` neu co host | Nhieu `r2v` |
| Asset consistency | It hon, co the khong can cast | Rat quan trong: cast/set/props |
| BGM | User chi dinh local mp3, mix global | Khong co tru khi user/the folder cung cap |
| Parallelism | Cao vi narration shots break chain | Vua, vi mot so shot chain de giu continuity |
| Review trong tam | logic/style/physics | cast_match/dialog_attribution/style |

