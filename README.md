# spark-video

> [中文版 / Chinese →](README.zh.md)

AI video production skill — premise → screenplay → storyboard → render
→ review → final mp4, with consistent characters / sets / props.
Cross-platform (Claude Code, Cursor, Qwen Code, Codex, …).

## Examples

> **Note:** The videos below were actually generated from **Chinese prompts** (see [`README.zh.md`](README.zh.md) for the originals). The prompts here are English translations for readability — spark-video works equally well in either language, but on-screen text, TTS narration, and rendered dialog will follow whichever language you write your prompt in.

<table>
<tr>
<th width="44%">📝 Prompt (translated)</th>
<th width="56%">🎬 Output</th>
</tr>

<tr>
<td valign="top">

**① J-drama · First Love** (≈2 min, 16:9)

> J-drama style. A high-school girl's sweet, awkward first-love story — heartwarming enough to make the viewer want to fall in love. About 2 minutes long. 16:9.

</td>
<td>

<video src="https://cloud.video.taobao.com/vod/ToFBk3q6IrT1L6k9TAW3Qu0GdJAWN80uyb75zNelvE8.mp4" controls muted></video>

</td>
</tr>

<tr>
<td valign="top">

**② Suspense · The Last Train** — narrator-only, no BGM, custom TTS voice

> A man boards a late-night express, asking every passenger their age — until the final reveal that he was reading lifespans, not ages.

<details>
<summary>Full prompt</summary>

Generate a suspense short film for me.

**Synopsis:** I boarded an express train. About ten minutes before midnight, at an intermediate stop, a man also got on. The moment the doors closed, he seemed to snap back to consciousness and began scanning the faces of the passengers around him. *"Forgive my rudeness — but are you 28 this year?"* he asked me. *"Yes, but how could you tell?"* I replied. He ignored me and turned to others. *"You're 45, aren't you?" — "That's right." — "And you, 62?" — "How did you know?"* He kept this up with every stranger in the car, as if able to read a person's age from their face. The next station was still about 15 minutes away, and every passenger watched him in fascinated silence. Finally he reached the last woman. *"You're 50?" — "Yes — but in five more minutes I'll turn 51!"* she answered, smiling. The man's face went deathly pale.

Use **narrator mode** — third-person voiceover. As the closing line, the narrator adds: *It turned out the numbers he saw were not ages, but lifespans. He realized everyone's number lined up too perfectly with their actual age, and guessed the train was about to crash. That's why he was frantically confirming ages — hoping to flee the moment they pulled into the next station. But now, it seems, it was already too late.*

- Narrator voice: `qwen3-tts` → **Ebona**
- Important: do **not** let the model generate any background music.

</details>

</td>
<td>

<video src="https://cloud.video.taobao.com/vod/MZx8KDUpGBygpU3SuTShGzyVxh0CbeJjpzhfNqSWz1Y.mp4" controls muted></video>

</td>
</tr>

<tr>
<td valign="top">

**③ Pop-sci · Why humans lose muscle easily** — local BGM file

> An entertaining pop-science video, under 3 minutes, explaining from a scientific angle why humans — compared to other mammals — have such a hard time maintaining strong muscles. Use `~/Documents/darktown-strutters-ball.mp3` as the background music.

</td>
<td>

<video src="https://cloud.video.taobao.com/vod/s589nKcgwi15bqIZyn8923w-F53_ZIDprlsmbaaodzo.mp4" controls muted></video>

</td>
</tr>

<tr>
<td valign="top">

**④ Product ad · iPhone Pro** — reference images + 5-segment script + looped BGM

> A high-end smartphone ad called **iPhone Pro**. Spokesperson reference: `jason1.jpg` / `jason2.jpg`; product shot: `product-item.webp`; pure voiceover (spokesperson never speaks); loop the BGM if it's too short.

<details>
<summary>Full prompt (5-segment script)</summary>

Create a high-end smartphone ad for me, named **iPhone Pro**.

**Ad copy (5 segments):**

1. *You — extraordinary. You love to surpass. You have dreams, you have power, and you never treat achievement as the finish line. Remember: your name is **Success**. iPhone Pro — titanium-alloy 24° golden-angle bevel cut, imported Dutch calfskin, retina HD display, 128 GB top-spec storage, 13 MP HD camera. A salute to a life of success.*
2. *iPhone Pro — your one-to-one private security key. The moment phone and owner are more than 10 meters apart, an alert fires automatically. The gap between "good" and "excellent" is short — and that gap is called **safety**. Forget it nearby and it reminds you; lose it and it alerts you. The phone stays close; the secrets stay safe.*
3. *iPhone Pro — invisible dialing, encrypted calls, traceless communication. Happiness is often shared, but pain is often hidden. This is what it means to be a man — your world, others don't get to understand. Invisible dialing, encrypted calls, traceless communication. Eloquent when speaking; composed when retreating.*
4. *Knowing how to live is what makes you good at work. iPhone Pro — dual password, dual space. Work and life stored separately, neither interferes with the other. Remember: running fast doesn't always win — never tripping is what success looks like. One phone, two passwords, two spaces, kept perfectly apart.*
5. *Success isn't about looking from afar — it's that you were standing on the heights all along, planning ahead, owning the future. That's iPhone Pro. That's what it means to hold the world. Peak ambition, titanium spirit, leather sensibility. Let us salute a life of success.*

**Assets:**

- Product image: `~/Documents/product-item.webp`
- Spokesperson references: `~/Documents/jason1.jpg`, `~/Documents/jason2.jpg`
- Background music: `~/Documents/励志奋斗.mp3` (loop if too short)
- All voiceover — the spokesperson never speaks on-camera

</details>

</td>
<td>

<video src="https://cloud.video.taobao.com/vod/x_UZpW3zyL0JC1x6uhATnVRwwrkq9PIEjIsaNuzUPZA.mp4" controls muted></video>

</td>
</tr>
</table>

## Install — just ask your agent

The whole install is **one prompt**. Open any agent that supports skills
(Claude Code, Cursor, Qwen Code, Gemini CLI, …) and paste:

> Install the spark-video skill for me:
> 1. Detect this OS's correct skills directory for the agent I'm running
>    in (e.g. `~/.claude/skills/`, `~/.qwen/skills/`,
>    `~/.cursor/skills/`, …) and `git clone
>    https://github.com/JohnKeating1997/spark-video.git` into it as
>    `spark-video`.
> 2. Tell me to open a new session so the skill gets loaded.
> 3. In the new session, read `spark-video/SKILL.md`, run
>    `./scripts/doctor.sh`, and install any missing deps (`bl`,
>    `ffmpeg`, `uv`) with my OS's package manager — ask before each
>    install command.
> 4. Ask whether to also clone the Shanyin craft references via
>    `./scripts/install-deps.sh` (failure is safe).
> 5. Re-run doctor and confirm everything is green.

That's it. No paths to memorize, no platform-specific commands to copy
— the agent reads `SKILL.md` (which contains the full install runbook)
and drives the rest.

<details>
<summary>Manual fallback (if your agent isn't skill-aware)</summary>

```bash
# Pick the path your platform expects:
git clone https://github.com/JohnKeating1997/spark-video.git \
  ~/.claude/skills/spark-video
# or  ~/.qwen/skills/spark-video
# or  ~/.cursor/skills/spark-video
# …
```

Then open a new agent session and say:
**"Set up spark-video for me."**
The agent will follow the install runbook in `SKILL.md`.

</details>

## Use it

In a new session, say one of:

**One-shot mode (recommended)**
> Use spark-video to make a 3-minute short. Project: demo, episode 1.
> Premise: [your story idea]

**Per-stage mode**
> Use spark-video's screenwriter to draft a script. Project demo
> episode 001. Premise: …

The agent reads `SKILL.md`, routes to the matching sub-skill, and runs
the 4+2 user-confirmation gate workflow.

## Outputs

```
projects/<project>/<episode>/
├── final/<project>-<episode>.mp4     ← deliverable
├── clips/*.mp4                       ← all rendered shots
├── reviews/*.json                    ← per-clip QA verdicts
└── logs/model_calls.jsonl            ← every prompt sent to every model
                                        (PE-friendly audit trail)
```

## Troubleshooting

Most of these you can just hand to the agent — say "fix X for me" and
it'll run the right command.

- After install the agent doesn't recognize `spark-video` → restart the
  agent / open a new session
- `bl: command not found` → `npm install -g bailian-cli && npx skills add modelstudioai/skills --all -g && bl auth login`
  (full install guide: <https://bailian.aliyun.com/cli/install.md>)
- `Permission denied: scripts/bl` → `chmod +x scripts/*.sh scripts/bl`
- Render seems stuck → `tail -f projects/<p>/<e>/logs/model_calls.jsonl | jq .`

## Update / Uninstall

Just ask your agent:

> Update spark-video.
> Uninstall spark-video.

Or do it manually:

```bash
# Update
cd ~/.claude/skills/spark-video && git pull

# Uninstall
rm -rf ~/.claude/skills/spark-video
```

## Want to look under the hood?

- Architecture + agent routing rules: [`SKILL.md`](SKILL.md)
- Per-sub-skill detailed docs: [`references/spark-video-*/SKILL.md`](references/)
- Per-script `--help`: `uv run scripts/<name>.py --help`
