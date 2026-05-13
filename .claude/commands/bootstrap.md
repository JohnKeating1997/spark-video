---
description: One-shot environment check + auto-fix. Run after a fresh clone or whenever `videogen doctor` complains.
argument-hint: (no args)
---

You are bootstrapping the videogen workspace. Your job is to **detect what's
missing and fix it**, asking the user only when a step truly needs human input
(e.g. an API key). Be idempotent — every check below should be safe to re-run.

Work through the list **in order**. After each step, print a one-line PASS /
FIXED / SKIPPED summary so the user can follow along.

### 1. System binaries

- `ffmpeg -version` — if missing:
  - macOS → `brew install ffmpeg`
  - Linux → tell the user the apt/yum command for their distro and stop (don't `sudo` without consent)
- `python3 --version` — require ≥ 3.11. If missing or too old, surface the
  detected version and instruct the user (do not auto-install Python).

### 2. Python package

- Try `./bin/videogen --version` (or `videogen --version`). If it fails with
  `ModuleNotFoundError` / `command not found`:
  - Prefer the existing `.venv/`: `source .venv/bin/activate && pip install -e .`
  - If no venv exists, create one: `python3 -m venv .venv && source .venv/bin/activate && pip install -e .`

### 3. `.env`

- If `.env` is missing, `cp .env.example .env` and tell the user to fill
  `DASHSCOPE_API_KEY` (get it at <https://help.aliyun.com/zh/model-studio/get-api-key>).
- If `.env` exists but `DASHSCOPE_API_KEY` is still the placeholder
  `sk-xxxxxxxx...`, prompt the user for the real key before proceeding.

### 4. Wrapped Shanyin skills

- Check that **both** of these files exist:
  - `.claude/skills/screenwriter/references/shanyin-screenwriting/SKILL.md`
  - `.claude/skills/video-director/references/shanyin-director/SKILL.md`
- If either is missing, run `bash scripts/install-shanyin-skills.sh`.
- This script clones two upstream repos via HTTPS — if it fails (network /
  auth), surface the error and stop; do **not** retry silently.

### 5. Git hooks (optional but recommended)

- If `.git/hooks/pre-commit` does not exist or doesn't reference
  `scripts/pre-commit`, run `bash scripts/install-hooks.sh`.

### 6. Final verification

- Run `./bin/videogen doctor` and surface its output verbatim.
- If doctor still reports red, do **not** declare success — list each red item
  and tell the user what to do next.

### Output format

End your reply with a short table:

| Step | Status |
|------|--------|
| ffmpeg | PASS / FIXED |
| python ≥ 3.11 | PASS / FIXED |
| videogen CLI | PASS / FIXED |
| .env | PASS / NEEDS USER (API key) |
| Shanyin skills | PASS / FIXED |
| Git hooks | PASS / FIXED / SKIPPED |
| videogen doctor | PASS / FAIL |

If anything is in `NEEDS USER` or `FAIL`, the next step is to fix that, not to
move on to `/cast-init` or `/episode`.
