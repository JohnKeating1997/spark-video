# spark-video

> [English version →](README.md)

AI 视频制作 skill — premise → 剧本 → 分镜 → 渲染 → 审片 → 成片 mp4,
角色/布景/道具一致。跨 agent 平台(Claude Code / Cursor / Qwen Code /
Codex / …)。

## 示例

<table>
<tr>
<th width="44%">📝 Prompt</th>
<th width="56%">🎬 成片</th>
</tr>

<tr>
<td valign="top">

**① 日剧风 · 青涩初恋**（≈2 分钟，16:9）

> 日剧风格，高中女生的青涩初恋故事，剧情高甜，让人看了想谈恋爱，2 分钟左右。16:9

</td>
<td>

<video src="https://cloud.video.taobao.com/vod/ToFBk3q6IrT1L6k9TAW3Qu0GdJAWN80uyb75zNelvE8.mp4" controls muted></video>

</td>
</tr>

<tr>
<td valign="top">

**② 悬疑短剧 · 末班车** — 纯旁白、无 BGM、指定 TTS 音色

> 一列午夜特快上，男子挨个询问乘客年龄；结尾揭示他看到的其实是寿命，火车即将出事——可惜已经来不及了。

<details>
<summary>展开完整 prompt</summary>

帮我生成一个悬疑短剧。

故事梗概：我搭上了一列特快车，大概在还差 10 分就午夜 12 点的时候，在中途站有一名男子也上了列车，他在车门关闭后，像是突然回复意识一般，开始左右环视着周遭乘客的脸。"恕我愚昧，请问您今年 28 岁吗？" 他如此地向我问道……一直到他问到最后一名女士。"您是 50 岁吗？""是的，不过还有五分钟就 51 岁了！" 那名女士如此微笑地回答道。霎时，那名男子的脸色铁青。

采用 **旁白模式**，第三人称叙事。结尾旁白加一句：原来，这个男子看到的数字，是寿命而不是年龄……可现在，似乎来不及了。

- 旁白音色：`qwen3-tts` → **Ebona**
- 注意：不要让模型生成背景音乐

</details>

</td>
<td>

<video src="https://cloud.video.taobao.com/vod/MZx8KDUpGBygpU3SuTShGzyVxh0CbeJjpzhfNqSWz1Y.mp4" controls muted></video>

</td>
</tr>

<tr>
<td valign="top">

**③ 趣味科普 · 人类肌肉之谜** — 指定本地 BGM 文件

> 3 分钟以内的趣味科普视频，从科学的角度介绍为什么人类相比其他哺乳动物，不容易保持强大的肌肉。背景音乐采用 `~/Documents/darktown-strutters-ball.mp3`。

</td>
<td>

<video src="https://cloud.video.taobao.com/vod/s589nKcgwi15bqIZyn8923w-F53_ZIDprlsmbaaodzo.mp4" controls muted></video>

</td>
</tr>

<tr>
<td valign="top">

**④ 产品广告 · iPhone Pro** — 参考图 + 5 段文案 + 循环 BGM

> 高端手机广告。代言人形象参考 `jason1.jpg` / `jason2.jpg`，产品图 `product-item.webp`，全旁白（代言人不说话），BGM 不够长则循环。

<details>
<summary>展开完整 prompt（5 段文案）</summary>

帮我创作一款高端手机的广告，名字叫 **iPhone Pro**。

**广告文案：**

1. 你，与众不同，你喜欢超越……iPhone Pro，钛合金 24° 黄金角立体切割……向成功的人生致敬。
2. 专属一对一保密钥匙。人机分离 10 米自动报警……忘带会提醒，丢失就报警，手机不忘带，机密不泄露。
3. 隐形拨号，加密通话，无痕迹沟通。幸福往往是分享，而苦痛却常常隐藏……能谈吐有方，会进退自如。
4. 双密码、双空间，工作生活分别存储，互不干扰。跑得快不一定赢，不跌跟头才是成功。
5. 顶峰的目标，钛金的气概，真皮的情怀，让我们向成功的人生致敬。

**素材：**

- 产品图：`~/Documents/product-item.webp`
- 代言人参考：`~/Documents/jason1.jpg`、`~/Documents/jason2.jpg`
- 背景音乐：`~/Documents/励志奋斗.mp3`（不够长可循环）
- 全旁白，代言人不说话

</details>

</td>
<td>

<video src="https://cloud.video.taobao.com/vod/x_UZpW3zyL0JC1x6uhATnVRwwrkq9PIEjIsaNuzUPZA.mp4" controls muted></video>

</td>
</tr>
</table>

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
