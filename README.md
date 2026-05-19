# spark-video

AI 视频制作 skill,跨 agent 平台(Claude Code / Qwen Code / …)。
故事点子 → 剧本 → 分镜 → 渲染 → 审片 → 成片 mp4,角色/布景/道具一致。

## 1. 装依赖(三个一行命令)

```bash
# Bailian CLI(模型网关,必装)
npm i -g @alibaba/bailian-cli && bl auth login

# ffmpeg(视频拼接,必装)
brew install ffmpeg                 # macOS
sudo apt install ffmpeg             # Ubuntu/Debian

# uv(Python 脚本运行器,必装,自动装脚本依赖)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

体检: `./scripts/doctor.sh`

## 2. 装 skill

```bash
# Claude Code
git clone https://github.com/<you>/spark-video ~/.claude/skills/spark-video

# Qwen Code(路径以平台文档为准)
git clone https://github.com/<you>/spark-video ~/.qwen/skills/spark-video

# 可选:拉 山音 编剧/导演 craft(失败也不影响主流程)
cd ~/.claude/skills/spark-video && ./scripts/install-deps.sh
```

## 3. 让 agent 用起来

把下面任一行贴到 agent 对话:

**一键模式(推荐)**
> 用 spark-video 帮我做一集 3 分钟短剧,项目叫 demo,第一集,
> premise:[你的故事点子]

**分步模式**
> 用 spark-video。先帮我写剧本(spark-video-screenwriter),
> 项目 demo episode 001,premise:…

Agent 会读 `SKILL.md` 自动路由到对应 sub-skill。

## 4. 产物在哪里

```
projects/<project>/<episode>/
├── final/<project>-<episode>.mp4     ← 成片
├── clips/*.mp4                       ← 所有 shot
├── reviews/*.json                    ← 逐 clip 评分
└── logs/model_calls.jsonl            ← 每一次模型调用的 prompt(PE 友好)
```

## 排障

- `bl: command not found` → 见第 1 步
- `Permission denied: scripts/bl` → `chmod +x scripts/*.sh scripts/bl`
- 渲染卡住 → `tail -f projects/<p>/<e>/logs/model_calls.jsonl | jq .`
- 子 skill 详细文档: `references/spark-video-*/SKILL.md`
