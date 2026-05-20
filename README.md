# spark-video

> [中文版 / Chinese →](README.zh.md)

AI video production skill — premise → screenplay → storyboard → render
→ review → final mp4, with consistent characters / sets / props.
Cross-platform (Claude Code, Qwen Code, …).

## Install (2 steps)

### Step 1 — clone into your agent's skills directory

```bash
# Claude Code (user-global, available in every project)
git clone https://github.com/<you>/spark-video ~/.claude/skills/spark-video

# Qwen Code (path may differ — check your platform docs)
git clone https://github.com/<you>/spark-video ~/.qwen/skills/spark-video
```

**Restart your agent** (or open a new session) so the skill gets loaded.

### Step 2 — let the agent install dependencies for you

In a new session, just say:

> Set up spark-video for me

The agent will:
- Detect missing dependencies (`bl`, `ffmpeg`, `uv`)
- Install them via your package manager (asking before each command)
- Optionally clone the upstream Shanyin craft references (failure is safe)
- Run a health check to confirm everything is ready

**You don't need to pre-install anything** (assuming you have `brew` on
macOS, `apt` on Ubuntu/Debian, or are using WSL on Windows).

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

- After install the agent doesn't recognize `spark-video` → restart the agent / open a new session
- `bl: command not found` → manual install: `npm i -g @alibaba/bailian-cli && bl auth login`
- `Permission denied: scripts/bl` → `chmod +x scripts/*.sh scripts/bl`
- Render seems stuck → `tail -f projects/<p>/<e>/logs/model_calls.jsonl | jq .`

## Update / Uninstall

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
