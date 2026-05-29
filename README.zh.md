# spark-video

> [English version →](README.md)

AI 视频制作 skill — premise → 剧本 → 分镜 → 渲染 → 审片 → 成片 mp4,
角色/布景/道具一致。跨 agent 平台(Claude Code / Cursor / Qwen Code /
Codex / …)。

## 安装 — 一句话交给 agent

整个安装就是**一段 prompt**。打开任意支持 skills 的 agent
(Claude Code / Cursor / Qwen Code / Gemini CLI / …),把下面这段粘进去:

> 帮我装 spark-video skill:
> 1. 识别我当前所在 agent 在这个操作系统下的 skills 目录
>    (比如 `~/.claude/skills/`、`~/.qwen/skills/`、
>    `~/.cursor/skills/` …),把
>    `https://github.com/JohnKeating1997/spark-video.git` clone 到那里,
>    目录名叫 `spark-video`。
> 2. 提醒我新开一个会话,让 skill 被加载。
> 3. 新会话里读 `spark-video/SKILL.md`,跑 `./scripts/doctor.sh`,
>    用我系统的包管理器装上缺的依赖(`bl` / `ffmpeg` / `uv`),
>    每条命令都先问我确认。
> 4. 问我要不要顺手 `./scripts/install-deps.sh` 拉 山音 craft 引用
>    (失败不影响主流程)。
> 5. 再跑一次 doctor,全绿后告诉我可以开工了。

完事。不需要记路径,也不需要复制 platform-specific 的命令 —— agent 读
`SKILL.md`(里面有完整的安装 runbook)自己驱动后面的步骤。

<details>
<summary>手动 fallback(如果你的 agent 不识别 skills)</summary>

```bash
# 挑你所在平台对应的目录:
git clone https://github.com/JohnKeating1997/spark-video.git \
  ~/.claude/skills/spark-video
# 或  ~/.qwen/skills/spark-video
# 或  ~/.cursor/skills/spark-video
# …
```

然后新开 agent 会话发一句:
**"帮我把 spark-video 装好"**
agent 会按 `SKILL.md` 里的安装 runbook 继续。

</details>

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

大多数情况直接交给 agent 处理 —— 说"帮我修 XX"就行。

- 安装后 agent 不认识 `spark-video` → 重启 agent / 新开会话
- `bl: command not found` → `npm install -g bailian-cli && npx skills add modelstudioai/skills --all -g && bl auth login`
  (完整安装说明：<https://bailian.aliyun.com/cli/install.md>)
- `Permission denied: scripts/bl` → `chmod +x scripts/*.sh scripts/bl`
- 渲染卡住 → `tail -f projects/<p>/<e>/logs/model_calls.jsonl | jq .`

## 更新 / 卸载

直接交给 agent:

> 帮我更新一下 spark-video。
> 帮我卸载 spark-video。

或者手动:

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
