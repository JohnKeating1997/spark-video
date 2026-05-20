---
name: spark-video
description: Production-grade AI video pipeline (screenplay → storyboard → render → review → stitched mp4) with consistent characters, sets, and props. Wraps DashScope models via the `bl` CLI. Use for short-form drama (drama mode) or explainer videos (narration mode), 3–10 minute episodes.
---

# spark-video — AI 视频制作 skill

## 总览

把一个故事点子(premise)做成 3–10 分钟、角色/布景/道具一致的成片。
流程: **剧本 → 分镜 → 渲染 → 审片 → 拼接**。
每段一个 sub-skill,本根 SKILL.md 是路由器。

## 开工前必读

### 1. 永远用 `./scripts/bl` 代替原生 `bl`
所有 prompt 被包装器记录到 `logs/model_calls.jsonl`。**直接调 `bl` 会漏日志** —
事后做 prompt engineering 时无从查。这是软约束,但是核心约定。

### 2. 上下文环境变量
切到一集前先 export:
```bash
export SPARK_VIDEO_PROJECT=<project_id>     # 例如 hf
export SPARK_VIDEO_EPISODE=<NN>             # 例如 001 → episode-001/
```
渲染单 shot 前再加:
```bash
export SPARK_VIDEO_SHOT=S01-001
export SPARK_VIDEO_PHASE=render             # render | review | rewrite | portrait | screenwriter | director | vfx-review | producer
```

### 3. Provider(默认 bl)
```bash
export SPARK_VIDEO_PROVIDER=bl              # 默认,覆盖 90% 用例
# export SPARK_VIDEO_PROVIDER=wan27         # 只在需要 wan2.7 精确末帧续接时
```

### 4. 项目目录结构
```
projects/<project>/
├── lore.md                              ← 世界设定(项目共享)
├── cast/<name>/{cast.md,*.png,*.mp3}    ← 主演
├── movie-set/<name>/{set.md,*.png}      ← 布景
├── props/<name>/{prop.md,*.png}         ← 关键道具
├── bgm/*.mp3                            ← BGM(可选)
└── <episode-NN>/
    ├── scenes/scene-NN.{md,ready,json}
    ├── script.md, storyboard.json
    ├── clips/, frames/, reviews/, logs/, final/
    └── shots_state.json
```

**铁律**:
- 一个布景文件夹 = 一种灯光状态(白天/夜晚分文件夹)
- 一个道具文件夹 = 一种叙事状态(完整/起皱分文件夹)
- 角色服装/发型/妆容**不写在 prompt 里**,靠立绘锁定;prompt 只写动作 + 表情,
  首次出场加年龄(如 "28 岁的陆辰")

## 首次安装(用户说"帮我装好 / 装依赖 / 体检")

按这个顺序处理:

1. **跑 `./scripts/doctor.sh`** —— 输出哪些依赖缺失。
2. **逐项装缺失的依赖**(请求用户确认每条命令再执行):
   - `bl: command not found` → `npm i -g @alibaba/bailian-cli && bl auth login`
   - `bl auth NOT logged in` → `bl auth login`
   - `ffmpeg / ffprobe not found` → macOS `brew install ffmpeg` · Ubuntu/Debian `sudo apt install -y ffmpeg`
   - `uv not found` → `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - `python3 too old` → 让用户装 Python 3.10+(常见: `brew install python@3.11` 或 `apt install python3.11`)
   - `scripts/bl missing or not executable` → `chmod +x scripts/bl scripts/*.sh`
3. **可选装 山音 craft 引用** —— `./scripts/install-deps.sh`(失败不影响,只是少了 craft 纹理)。问用户要不要装,不要默认装。
4. **再跑一次 `./scripts/doctor.sh` 确认全绿**,然后告知用户可以开始用了。

## 子 skill 路由表

| 我要…… | 去读 | 职责 |
|---|---|---|
| 一键做完整集 | `references/spark-video-episode/SKILL.md` | 全流程 autopilot + 4 gate |
| premise → 剧本 | `references/spark-video-screenwriter/SKILL.md` | 写 `scenes/scene-NN.md`,一次一场景 |
| 剧本 → 分镜 | `references/spark-video-director/SKILL.md` | 写 `scenes/scene-NN.json`,validate schema |
| 渲染前查 storyboard 质量 | `references/spark-video-vfx-review/SKILL.md` | 静态质量门(可选) |
| 渲染 / 审片 / 重渲 | `references/spark-video-clip-review/SKILL.md` | ACCEPT/REJECT/rewrite/escalate 状态机 |
| 角色/布景/道具 scaffold | `references/spark-video-cast/SKILL.md` | 建文件夹 + `bl image generate` 出参考图 |

**进阶 craft**: 若 `references/shanyin/screenwriting-master/SKILL.md` 或
`references/shanyin/director-master/SKILL.md` 存在,screenwriter / director
优先采用其规则。装失败不影响主流程,只是少了风格化纹理。
拉法见 `./scripts/install-deps.sh`。

## 常用脚本

| 命令 | 用途 |
|---|---|
| `./scripts/bl <args>` | 透明日志包装,**替代原生 bl** |
| `uv run scripts/storyboard.py {validate\|compile\|estimate\|graph}` | storyboard 校验 / 合并 / 估算 / 算并行图 |
| `uv run scripts/render_shot.py --shot <id> --kind <k> --prompt "..." --media a.png b.png` | 渲染单 shot,按 `SPARK_VIDEO_PROVIDER` 分发 |
| `uv run scripts/scaffold.py {scene\|cast\|set\|prop\|bgm\|lore} ...` | 模板生成 |
| `uv run scripts/stitch.py` | ffmpeg 拼接 + BGM 混音 + 旁白音轨替换 |
| `./scripts/doctor.sh` | 体检(bl/ffmpeg/uv) |
| `./scripts/install-deps.sh` | 拉 山音 craft 引用(可选) |

各脚本 `--help` 查参数。

## 输出契约

`render_shot.py` 渲染完成后 stdout 输出:
```json
{"shot_id":"S01-001","version":1,"video_path":"...","last_frame_path":"...","duration_s":15.0,"provider":"bl","model":"happyhorse-1.0-r2v","elapsed_s":47.2}
```
退出码: 0 ok · 1 provider 错 · 2 参数错 · 3 超时。

`shots_state.json` 是单一信源 —— **只有 `render_shot.py` 写**,其它脚本只读。
`reviews/<shot>-verN.json` 由 agent 在调完 `bl omni` 后直接 Write。

## 模式

- **drama**(默认): 每 shot 带对白,长 clip,适合 2–5 分钟短剧
- **narration**(旁白解说): 旁白 shot 短(3–6s)+ `bl speech synthesize` 替换音轨;
  对白 shot 同 drama。最大化并行,适合 "10 分钟带你看完 XX"

`uv run scripts/storyboard.py compile --mode narration` 锁定模式,
写入 `Storyboard.mode`。

## 不要做的事

- ❌ 直接调原生 `bl`(漏日志)
- ❌ 手改 `shots_state.json`
- ❌ 在 prompt 里描述角色服装/发型/妆容
- ❌ 同一布景 day/night 共用一个文件夹
- ❌ 同一道具 完整/起皱 共用一个文件夹
- ❌ 跳过 `storyboard.py estimate` 直接渲(可能炸预算)
- ❌ 渲染失败不读 `logs/model_calls.jsonl` 就盲目重试
