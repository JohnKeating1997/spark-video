# Setup and Repair

Read this file only when `doctor.sh --quick --json` returns `"ok": false`
or the user explicitly asks to install, set up, repair, or diagnose
spark-video.

## Fast path

Resolve the installed skill directory as `SPARK_VIDEO_SKILL_DIR`, keep the
current working directory as the user's video workspace, then run:

```bash
"$SPARK_VIDEO_SKILL_DIR/scripts/doctor.sh" --quick --json
```

If `"ok": true`, do not run setup commands. Optional Shanyin warnings do
not block normal use.

## Repair path

When the quick check fails, run:

```bash
"$SPARK_VIDEO_SKILL_DIR/scripts/doctor.sh" --install-plan --json
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

The references are stored in the current workspace at
`.spark-video/references/shanyin/` unless `SPARK_VIDEO_SHANYIN_DIR` is set.

## Session Reload

After a new skill installation or update, tell the user to open a new
agent session so the skill metadata and descriptions are reloaded.
