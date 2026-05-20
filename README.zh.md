# spark-video

> [English version →](README.md)

AI 视频制作 skill — premise → 剧本 → 分镜 → 渲染 → 审片 → 成片 mp4,
角色/布景/道具一致。跨 agent 平台(Claude Code / Qwen Code / …)。

## 安装(两步)

### Step 1 — clone 到 skills 目录

```bash
# Claude Code(用户级,所有项目可用)
git clone https://github.com/<you>/spark-video ~/.claude/skills/spark-video

# Qwen Code(以平台文档为准)
git clone https://github.com/<you>/spark-video ~/.qwen/skills/spark-video
```

**重启你的 agent 一次**(或新开会话),让 skill 被加载。

### Step 2 — 让 agent 帮你装依赖

新会话里发一句:

> 帮我把 spark-video 装好

agent 会自动:
- 检测缺失的依赖(`bl` / `ffmpeg` / `uv`)
- 用对应包管理器装好(请求你确认)
- 拉可选的 山音 craft 引用(失败也不影响主流程)
- 跑体检确认就绪

**你不需要预装任何东西,agent 都会自己搞定**(但你要在 macOS 上有 `brew`,
或在 Ubuntu/Debian 上有 `apt`,或在 Windows 上用 WSL)。

## 用起来

新会话发一句任意一种:

**一键模式(推荐)**
> 用 spark-video 帮我做一集 3 分钟短剧,项目叫 demo,第一集,
> premise:[你的故事点子]

**分步模式**
> 用 spark-video 的 screenwriter 帮我写剧本,项目 demo episode 001,
> premise:…

agent 读 `SKILL.md` 自动路由到对应 sub-skill,按 4+2 gate 流程跑。

## 产物

```
projects/<project>/<episode>/
├── final/<project>-<episode>.mp4     ← 成片
├── clips/*.mp4                       ← 所有 shot
├── reviews/*.json                    ← 逐 clip 评分
└── logs/model_calls.jsonl            ← 每一次模型调用的 prompt(PE 友好)
```

## 排障

- 安装后 agent 不认识 `spark-video` → 重启 agent / 新开会话
- `bl: command not found` → agent 没装成,手动: `npm i -g @alibaba/bailian-cli && bl auth login`
- `Permission denied: scripts/bl` → `chmod +x scripts/*.sh scripts/bl`
- 渲染卡住 → `tail -f projects/<p>/<e>/logs/model_calls.jsonl | jq .`

## 更新 / 卸载

```bash
# 更新
cd ~/.claude/skills/spark-video && git pull

# 卸载
rm -rf ~/.claude/skills/spark-video
```

## 想看细节?

- 架构 + agent 调度规则: [`SKILL.md`](SKILL.md)
- 6 个子技能的详细文档: [`references/spark-video-*/SKILL.md`](references/)
- 每个脚本的 `--help`: 用 `uv run scripts/<name>.py --help`
