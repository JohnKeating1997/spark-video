# spark-video

> [中文版 / Chinese →](README.zh.md)

AI video production skill — premise → screenplay → storyboard → render
→ review → final mp4, with consistent characters / sets / props.
Cross-platform (Claude Code, Cursor, Qwen Code, Codex, …).

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
- `bl: command not found` → `npm i -g @alibaba/bailian-cli && bl auth login`
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
