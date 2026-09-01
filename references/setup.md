# Setup and Repair

Read this file only when `doctor.sh --quick --json` returns `"ok": false`
or the user explicitly asks to install, set up, repair, or diagnose
spark-video.

Use `scripts/doctor.sh` on Unix-like systems and `scripts/doctor.ps1` on
native Windows PowerShell. The two entry points return the same JSON contract.

## Fast path

Resolve the installed skill directory as `SPARK_VIDEO_SKILL_DIR`, keep the
current working directory as the user's video workspace, then run:

```bash
"$SPARK_VIDEO_SKILL_DIR/scripts/doctor.sh" --quick --json
```

```powershell
& "$env:SPARK_VIDEO_SKILL_DIR\scripts\doctor.ps1" -Quick -Json
```

If `"ok": true`, do not run setup commands. Optional Shanyin warnings do
not block normal use.

## Repair path

When the quick check fails, run:

```bash
"$SPARK_VIDEO_SKILL_DIR/scripts/doctor.sh" --install-plan --json
```

```powershell
& "$env:SPARK_VIDEO_SKILL_DIR\scripts\doctor.ps1" -InstallPlan -Json
```

For each action where `required` is `true`:

1. Tell the user what is missing.
2. Ask before running each command in that action's `commands` array.
3. Run only the commands the user approves.
4. Re-run `doctor.sh --quick --json`.

If required checks still fail, run the human-readable report:

```bash
"$SPARK_VIDEO_SKILL_DIR/scripts/doctor.sh" --full
```

Use the full report to explain the remaining blocker.

## Optional Shanyin References

If the install plan includes `shanyin-references`, ask the user whether
to clone the optional craft references. Failure is safe; the pipeline
falls back to the baked-in spark-video references.

Only run this command after the user agrees:

```bash
"$SPARK_VIDEO_SKILL_DIR/scripts/install-deps.sh"
```

On native Windows PowerShell, run
`& "$env:SPARK_VIDEO_SKILL_DIR\scripts\install-deps.ps1"`.

The references are stored in the current workspace at
`.spark-video/references/shanyin/` unless `SPARK_VIDEO_SHANYIN_DIR` is set.

## Optional Bailian CLI

Normal image and video generation uses `wan-cli`; `bl` is not part of the
default installation. Require `bl` when the selected video provider is `bl`;
otherwise offer it as an optional action when the user wants
narration TTS or bl-based clip review. For narration, use the narration-aware
check so the action becomes required for that chosen run:

```bash
"$SPARK_VIDEO_SKILL_DIR/scripts/doctor.sh" --quick --json --narration
"$SPARK_VIDEO_SKILL_DIR/scripts/doctor.sh" --install-plan --json --narration
```

On native Windows PowerShell, use `doctor.ps1 -Quick -Json -Narration`, then
`doctor.ps1 -InstallPlan -Json -Narration` when repair is required.

Ask separately before installing `bailian-cli` or starting `bl auth login`.
The pipeline calls a fixed, narrow set of `bl` commands through its own wrapper,
so do not install the optional Bailian agent skill as part of spark-video setup.
In particular, do not use `npx skills add ... --all`: in the skills installer,
`--all` also targets every supported agent and can create unrelated agent
directories. Re-run the narration check after authentication.

## Session Reload

After a new skill installation or update, tell the user to open a new
agent session so the skill metadata and descriptions are reloaded.
