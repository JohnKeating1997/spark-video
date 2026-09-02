# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
gate.py — deterministic "did we actually do it?" verifier for the pipeline.

This is the *verify-don't-constrain* half of the stability story. It does
NOT tell an agent how to do its work and it does NOT replace the human
confirmation gates — it just checks that the mandatory, no-judgment
artifacts a stage is supposed to leave behind actually exist and are
internally consistent. Inferior agents that "forget" to score a clip or
to build the viewer get caught here instead of shipping a broken episode.

It reads only files (stdlib, no pydantic / no network) so it can run
anywhere — in a skill step, in a CI check, or wired to a framework "stop"
hook (Cursor / Claude Code) so the agent cannot end its turn while a
mandatory artifact is missing. Full schema validation still lives in
`storyboard.py validate`; this is cross-artifact completeness.

Gates (mirror the producer's user-confirmation gates):
    script      GATE 1 — script.md present
    storyboard  GATE 2 — storyboard.json present + static panels confirmed
    render      GATE 3 — every shot rendered, scored, and won (or escalated)
    final       GATE 4 — final mp4 + a fresh viewer.html exist
    all         run every gate and report a matrix

Usage:
    SPARK_VIDEO_PROJECT=hf SPARK_VIDEO_EPISODE=001 \\
        uv run scripts/gate.py check render
    uv run scripts/gate.py check all --json
    uv run scripts/gate.py check render --project hf --episode 001 --json

Exit codes:
    0 = gate passed (all error-severity checks ok)
    1 = gate failed (at least one error-severity check failed)
    2 = usage / precondition error (e.g. project/episode not set)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from lib.env import load_pwd_dotenv  # noqa: E402
from lib.shot_contract import contract_mismatches  # noqa: E402

load_pwd_dotenv()

GATES = ("script", "storyboard", "render", "final")


def _projects_root() -> Path:
    return Path(os.environ.get("VIDEOGEN_PROJECTS_DIR", "./projects")).resolve()


def _normalize_episode(ep: str) -> str:
    ep = ep.strip()
    return ep if ep.startswith("episode-") or ep.startswith("episode_") else f"episode-{ep}"


def _threshold() -> float:
    for n in ("SPARK_VIDEO_REVIEW_THRESHOLD", "VIDEOGEN_REVIEW_THRESHOLD"):
        v = os.environ.get(n)
        if v:
            try:
                return float(v)
            except ValueError:
                pass
    return 7.0


def _load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _probe_duration(path: Path) -> float:
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "csv=p=0", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return float(proc.stdout.strip()) if proc.returncode == 0 else 0.0
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def _shots(sb: dict) -> list[dict]:
    """Pull the flat shot list from a compiled storyboard (top-level or nested)."""
    if isinstance(sb.get("shots"), list):
        return [s for s in sb["shots"] if isinstance(s, dict)]
    out: list[dict] = []
    for sc in sb.get("scenes", []) or []:
        if isinstance(sc, dict) and isinstance(sc.get("shots"), list):
            out.extend(s for s in sc["shots"] if isinstance(s, dict))
    return out


def _manifest_entries(data: object, plural_key: str) -> dict[str, dict]:
    """Normalize current flat manifests and older nested manifest shapes."""
    if not isinstance(data, dict):
        return {}
    bucket = data.get(plural_key, data)
    if isinstance(bucket, dict):
        return {
            str(name): entry
            for name, entry in bucket.items()
            if isinstance(entry, dict)
        }
    if isinstance(bucket, list):
        return {
            str(entry.get("name")): entry
            for entry in bucket
            if isinstance(entry, dict) and entry.get("name")
        }
    return {}


def _entry_has_image(entry: dict) -> bool:
    """A generated local image is required; stale manifest paths do not count."""
    paths = entry.get("images") or entry.get("images_local") or []
    if isinstance(paths, str):
        paths = [paths]
    if entry.get("image_local"):
        paths = [entry["image_local"], *paths]
    return any(
        isinstance(raw, str) and Path(raw).expanduser().is_file()
        for raw in paths
    )


def _check_referenced_assets(r: "GateResult", ep_dir: Path, sb: dict) -> None:
    """Block GATE 1 when storyboard-referenced consistency assets lack images."""
    referenced: dict[str, set[str]] = {
        "cast": set(),
        "sets": set(),
        "props": set(),
    }
    for shot in _shots(sb):
        referenced["cast"].update(str(x) for x in shot.get("characters", []) if x)
        referenced["props"].update(str(x) for x in shot.get("props", []) if x)
        if shot.get("set_id"):
            referenced["sets"].add(str(shot["set_id"]))
    for scene in sb.get("scenes", []) or []:
        if isinstance(scene, dict) and scene.get("set_id"):
            referenced["sets"].add(str(scene["set_id"]))

    specs = (
        ("cast", "cast.json", "cast", "characters"),
        ("sets", "movie_set.json", "sets", "movie-sets"),
        ("props", "props.json", "props", "props"),
    )
    for ref_key, filename, plural_key, label in specs:
        names = referenced[ref_key]
        entries = _manifest_entries(_load_json(ep_dir / filename), plural_key)
        missing = sorted(name for name in names if not _entry_has_image(entries.get(name, {})))
        r.add(
            f"referenced {label} have local reference images",
            not missing,
            f"missing: {missing}" if missing else f"{len(names)} referenced",
        )


# --------------------------------------------------------------------------- model

@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    severity: str = "error"  # "error" blocks the gate; "warn" is advisory


@dataclass
class GateResult:
    gate: str
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.checks if c.severity == "error")

    def add(self, name: str, ok: bool, detail: str = "", severity: str = "error") -> None:
        self.checks.append(Check(name, ok, detail, severity))


# --------------------------------------------------------------------------- gates

def gate_script(ep_dir: Path) -> GateResult:
    r = GateResult("script")
    script = ep_dir / "script.md"
    text = script.read_text(encoding="utf-8") if script.exists() else ""
    r.add("script.md exists & non-empty", bool(text.strip()),
          str(script) if not text.strip() else f"{len(text)} chars")

    scenes_dir = ep_dir / "scenes"
    md = sorted(scenes_dir.glob("scene-*.md")) if scenes_dir.exists() else []
    js = sorted(scenes_dir.glob("scene-*.json")) if scenes_dir.exists() else []
    r.add("at least one scene-*.md", bool(md), f"{len(md)} found", severity="warn")
    r.add("director done (scene-*.json count == scene-*.md count)",
          bool(md) and len(js) == len(md), f"{len(md)} md / {len(js)} json",
          severity="warn")
    storyboard = _load_json(ep_dir / "storyboard.json")
    if isinstance(storyboard, dict):
        _check_referenced_assets(r, ep_dir, storyboard)
    else:
        r.add("reference asset completeness", False,
              "storyboard.json missing or invalid — compile before GATE 1")
    return r


def gate_storyboard(ep_dir: Path) -> GateResult:
    r = GateResult("storyboard")
    sb_path = ep_dir / "storyboard.json"
    if not sb_path.exists():
        r.add("storyboard.json exists", False,
              f"{sb_path} missing — run storyboard.py compile")
        return r
    r.add("storyboard.json exists", True, str(sb_path))
    sb = _load_json(sb_path)
    if sb is None:
        r.add("storyboard.json is valid JSON", False, "parse error")
        return r
    r.add("storyboard.json is valid JSON", True)

    shots = _shots(sb)
    r.add("has at least one shot", bool(shots), f"{len(shots)} shots")

    # Light structural checks (full schema check = `storyboard.py validate`).
    bad = [s.get("id", "<no-id>") for s in shots
           if not s.get("id") or not (s.get("prompt") or "").strip()]
    r.add("every shot has id + non-empty prompt", not bad,
          f"offenders: {bad[:5]}" if bad else "")
    ids = [s.get("id") for s in shots if s.get("id")]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    r.add("no duplicate shot ids", not dupes, f"dupes: {dupes}" if dupes else "")
    incomplete_cinematic_contracts = [
        s.get("id", "<no-id>")
        for s in shots
        if not str(s.get("camera_path") or "").strip()
        or not str(s.get("end_composition") or "").strip()
    ]
    r.add(
        "every shot has camera path + ending composition",
        not incomplete_cinematic_contracts,
        (
            f"offenders: {incomplete_cinematic_contracts[:8]}"
            if incomplete_cinematic_contracts
            else ""
        ),
    )
    video_model = sb.get("video_model") or "wan3.0"
    duration_ceiling = 30 if video_model == "wan3.0" else 15
    over_limit = [
        shot.get("id", "<unknown>")
        for shot in shots
        if isinstance(shot.get("duration"), (int, float))
        and shot["duration"] > duration_ceiling
    ]
    r.add(
        f"shot durations fit {video_model} capability",
        not over_limit,
        f"over {duration_ceiling}s: {over_limit[:8]}" if over_limit else "",
    )
    unjustified_long_takes = [
        shot.get("id", "<unknown>")
        for shot in shots
        if isinstance(shot.get("duration"), (int, float))
        and shot["duration"] > 15
        and not str(shot.get("long_take_reason") or "").strip()
    ]
    missing_long_timelines = [
        shot.get("id", "<unknown>")
        for shot in shots
        if isinstance(shot.get("duration"), (int, float))
        and shot["duration"] > 15
        and not (shot.get("beats") or [])
    ]
    r.add(
        "exceptional long takes are justified",
        not unjustified_long_takes,
        (
            f"missing long_take_reason: {unjustified_long_takes[:8]}"
            if unjustified_long_takes else ""
        ),
    )
    r.add(
        "exceptional long takes have a timed action plan",
        not missing_long_timelines,
        (
            f"missing timeline: {missing_long_timelines[:8]}"
            if missing_long_timelines else ""
        ),
    )

    audio = sb.get("audio") if isinstance(sb.get("audio"), dict) else None
    r.add("episode audio contract exists", audio is not None,
          "recompile with an explicit --audio-mode" if audio is None else "")
    if audio:
        audio_mode = audio.get("mode")
        bad_audio: list[str] = []
        if audio_mode == "presenter_voiceover":
            if not audio.get("presenter") or not audio.get("voice"):
                bad_audio.append("presenter/voice missing")
            if audio.get("model_audio_policy") != "strip_all":
                bad_audio.append("model_audio_policy must be strip_all")
            for shot in shots:
                source = shot.get("speech_source")
                if source != "post_tts":
                    bad_audio.append(f"{shot.get('id')}: source must be post_tts")
                if source == "post_tts" and shot.get("speaker") != audio.get("presenter"):
                    bad_audio.append(f"{shot.get('id')}: wrong speaker")
                if (
                    source == "post_tts"
                    and shot.get("narrator_voice")
                    and shot.get("narrator_voice") != audio.get("voice")
                ):
                    bad_audio.append(f"{shot.get('id')}: voice override")
        elif audio_mode == "native_dialogue":
            bad_audio.extend(
                f"{shot.get('id')}: post_tts"
                for shot in shots if shot.get("speech_source") == "post_tts"
            )
        elif audio_mode != "hybrid":
            bad_audio.append(f"unknown mode {audio_mode!r}")
        r.add(
            "shot audio sources follow the episode contract",
            not bad_audio,
            f"violations: {bad_audio[:8]}" if bad_audio else audio_mode,
        )
    r.add("run `storyboard.py validate` for full schema lint", True,
          "reminder", severity="warn")

    panels_dir = ep_dir / "storyboard-panels"
    manifest = panels_dir / "panels.json"
    confirmed = panels_dir / "CONFIRMED"
    skip = os.environ.get("SPARK_VIDEO_SKIP_ANIMATIC_GATE", "").lower() in {
        "1", "true", "yes", "y", "on",
    }
    if skip:
        r.add("static storyboard reference images confirmed", True,
              "skipped by SPARK_VIDEO_SKIP_ANIMATIC_GATE", severity="warn")
    else:
        r.add("static storyboard reference manifest exists", manifest.exists(),
              str(manifest) if manifest.exists()
              else f"{manifest} missing — run `uv run scripts/storyboard.py animatic`")
        panel_data = _load_json(manifest) or {}
        panels = panel_data.get("panels", []) or []
        panel_shot_ids = {
            panel.get("shots", [None])[0]
            for panel in panels
            if isinstance(panel, dict) and len(panel.get("shots") or []) == 1
        }
        missing_panels = [shot_id for shot_id in ids if shot_id not in panel_shot_ids]
        unselected = []
        invalid = []
        for panel in panels:
            if not isinstance(panel, dict):
                continue
            shot_id = str((panel.get("shots") or [panel.get("id", "<unknown>")])[0])
            selected = panel.get("selected_candidate")
            candidates = {
                candidate.get("id"): candidate
                for candidate in panel.get("candidates", []) or []
                if isinstance(candidate, dict) and candidate.get("id")
            }
            if not selected:
                unselected.append(shot_id)
            elif selected not in candidates or not (
                candidates[selected].get("image_url")
                or candidates[selected].get("image")
            ):
                invalid.append(shot_id)
        selections_ok = (
            bool(panels) and not missing_panels and not unselected and not invalid
        )
        detail = "all shots selected"
        if missing_panels:
            detail = f"missing panels: {missing_panels[:8]}"
        elif unselected:
            detail = f"not selected: {unselected[:8]}"
        elif invalid:
            detail = f"invalid selection: {invalid[:8]}"
        r.add("one storyboard candidate selected per shot", selections_ok, detail)
        r.add("static storyboard reference images confirmed", confirmed.exists(),
              str(confirmed) if confirmed.exists()
              else f"{confirmed} missing — review reference images, then run "
              "`uv run scripts/storyboard.py animatic --confirm`")
        stale_contracts = contract_mismatches(sb, panel_data)
        r.add(
            "confirmed storyboard contracts still match storyboard.json",
            not stale_contracts,
            f"changed after approval: {stale_contracts[:8]}" if stale_contracts else "",
        )
    return r


def gate_render(ep_dir: Path) -> GateResult:
    r = GateResult("render")
    sb = _load_json(ep_dir / "storyboard.json")
    if sb is None:
        r.add("storyboard.json present", False, "compile the storyboard first")
        return r
    shots = _shots(sb)
    if not shots:
        r.add("storyboard has shots", False)
        return r

    state = _load_json(ep_dir / "shots_state.json")
    if state is None:
        r.add("shots_state.json present", False, "nothing has been rendered yet")
        return r
    r.add("shots_state.json present", True)

    clips_dir = ep_dir / "clips"
    thr = _threshold()
    not_won: list[str] = []
    missing_clip: list[str] = []
    unscored: list[str] = []          # winner has no numeric review score
    review_errors: list[str] = []     # review ran but verdict ERROR/unknown
    failed_reviews: list[str] = []    # automatic winner still carries REJECT
    manual_rejects: list[str] = []    # explicit best-of-N selection
    blocking_reviews: list[str] = []
    below_thr: list[str] = []         # accepted under threshold (best-of-N)

    for shot in shots:
        sid = shot.get("id")
        if not sid:
            continue
        entry = state.get(sid) or {}
        winner = entry.get("winner_version")
        if not winner:
            not_won.append(sid)
            continue
        if not (clips_dir / f"{sid}.mp4").exists():
            missing_clip.append(sid)
        attempts = entry.get("attempts", []) or []
        wa = next((a for a in attempts if a.get("version") == winner), None)
        review = (wa or {}).get("review") or {}
        score = review.get("score")
        verdict = review.get("verdict")
        blocking_issues = review.get("blocking_issues") or []
        if blocking_issues:
            blocking_reviews.append(sid)
        if verdict == "REJECT":
            (manual_rejects if entry.get("manual_acceptance")
             else failed_reviews).append(sid)
        if isinstance(score, (int, float)):
            if score < thr:
                below_thr.append(f"{sid}({score})")
        elif verdict in ("ERROR", None, ""):
            # No numeric score AND no clean verdict → scoring was skipped or failed.
            (review_errors if verdict == "ERROR" else unscored).append(sid)

    n = len(shots)
    r.add("every shot has a winner_version", not not_won,
          f"{n - len(not_won)}/{n} won; missing: {not_won[:8]}" if not_won
          else f"{n}/{n}")
    r.add("every winner clip exists on disk", not missing_clip,
          f"missing clips/<id>.mp4: {missing_clip[:8]}" if missing_clip else "")
    r.add("every winner is scored or explicitly skipped", not unscored,
          f"UNSCORED (scoring skipped?): {unscored[:8]}" if unscored else "")
    r.add("no winner left with a failed review", not review_errors,
          f"review ERROR: {review_errors[:8]}" if review_errors else "",
          severity="warn")
    r.add(
        "no winner carries a REJECT verdict",
        not failed_reviews,
        f"REJECT winners: {failed_reviews[:8]}" if failed_reviews else "",
    )
    r.add(
        "no winner carries blocking review issues",
        not blocking_reviews,
        f"blocking issues: {blocking_reviews[:8]}" if blocking_reviews else "",
    )
    r.add("accepted-below-threshold shots (best-of-N)", True,
          (
              f"{below_thr[:8]} (threshold {thr:g}); "
              f"manually selected REJECT: {manual_rejects[:8]}"
              if below_thr or manual_rejects
              else f"none under {thr:g}"
          ), severity="warn")

    esc = _load_json(ep_dir / "needs_director_rewrite.json")
    open_esc = (esc or {}).get("shots") if isinstance(esc, dict) else None
    r.add("no unresolved director escalation", not open_esc,
          f"needs_director_rewrite.json open for: {open_esc}" if open_esc else "")
    return r


def gate_final(ep_dir: Path) -> GateResult:
    r = GateResult("final")
    final_dir = ep_dir / "final"
    mp4s = [p for p in final_dir.glob("*.mp4") if p.stat().st_size > 0] \
        if final_dir.exists() else []
    r.add("final/*.mp4 exists & non-empty", bool(mp4s),
          f"{[p.name for p in mp4s]}" if mp4s else "run stitch.py")

    viewer = ep_dir / "viewer.html"
    r.add("viewer.html exists", viewer.exists(),
          str(viewer) if not viewer.exists() else "")
    if viewer.exists() and mp4s:
        newest_mp4 = max(p.stat().st_mtime for p in mp4s)
        fresh = viewer.stat().st_mtime >= newest_mp4 - 1  # 1s slack
        r.add("viewer.html is newer than final mp4", fresh,
              "viewer is stale — re-run build_viewer.py / stitch.py" if not fresh
              else "", severity="warn")
    storyboard = _load_json(ep_dir / "storyboard.json") or {}
    audio = storyboard.get("audio") if isinstance(storyboard.get("audio"), dict) else {}
    if audio.get("mode") == "presenter_voiceover":
        audio_manifest_path = final_dir / "audio_manifest.json"
        audio_manifest = _load_json(audio_manifest_path)
        r.add(
            "presenter audio manifest exists",
            isinstance(audio_manifest, dict),
            str(audio_manifest_path) if audio_manifest is None else "",
        )
        if isinstance(audio_manifest, dict):
            entries = audio_manifest.get("shots") or []
            voices = {
                entry.get("voice")
                for entry in entries
                if isinstance(entry, dict)
                and entry.get("speech_source") == "post_tts"
                and entry.get("voice")
            }
            kept = [
                entry.get("shot_id") for entry in entries
                if isinstance(entry, dict) and entry.get("model_audio") == "kept"
            ]
            r.add(
                "presenter voice is uniform and model audio is removed",
                len(voices) <= 1 and not kept,
                f"voices={sorted(voices)} kept_model_audio={kept[:8]}",
            )
    target = storyboard.get("target_duration_s")
    if mp4s and isinstance(target, (int, float)) and target > 0:
        final_mp4 = max(mp4s, key=lambda path: path.stat().st_mtime)
        duration = _probe_duration(final_mp4)
        tolerance = max(3.0, float(target) * 0.05)
        within_target = duration > 0 and abs(duration - float(target)) <= tolerance
        r.add(
            "final duration matches target budget",
            within_target,
            (
                f"actual={duration:.2f}s target={float(target):.2f}s "
                f"tolerance=±{tolerance:.2f}s"
            ),
        )
    return r


_GATE_FNS = {
    "script": gate_script,
    "storyboard": gate_storyboard,
    "render": gate_render,
    "final": gate_final,
}


# ---------------------------------------------------------------------------- output

_MARK = {("error", True): "[ ok ]", ("error", False): "[FAIL]",
         ("warn", True): "[ ok ]", ("warn", False): "[warn]"}


def _print_human(results: list[GateResult]) -> None:
    for res in results:
        status = "PASS" if res.passed else "FAIL"
        print(f"GATE {res.gate}: {status}")
        for c in res.checks:
            mark = _MARK[(c.severity, c.ok)]
            line = f"  {mark} {c.name}"
            if c.detail:
                line += f" — {c.detail}"
            print(line)
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check", help="verify a gate's mandatory artifacts")
    p.add_argument("gate", choices=[*GATES, "all"])
    p.add_argument("--project", default=None, help="default: $SPARK_VIDEO_PROJECT")
    p.add_argument("--episode", default=None, help="default: $SPARK_VIDEO_EPISODE")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    project = args.project or os.environ.get("SPARK_VIDEO_PROJECT")
    episode = args.episode or os.environ.get("SPARK_VIDEO_EPISODE")
    if not project or not episode:
        print("ERROR: set SPARK_VIDEO_PROJECT and SPARK_VIDEO_EPISODE "
              "(or pass --project/--episode)", file=sys.stderr)
        return 2

    ep_dir = _projects_root() / project / _normalize_episode(episode)
    if not ep_dir.exists():
        print(f"ERROR: episode dir not found: {ep_dir}", file=sys.stderr)
        return 2

    gates = list(GATES) if args.gate == "all" else [args.gate]
    results = [_GATE_FNS[g](ep_dir) for g in gates]
    overall = all(res.passed for res in results)

    if args.json:
        print(json.dumps({
            "project": project,
            "episode": _normalize_episode(episode),
            "requested": args.gate,
            "passed": overall,
            "gates": [{
                "gate": res.gate,
                "passed": res.passed,
                "checks": [vars(c) for c in res.checks],
            } for res in results],
        }, ensure_ascii=False, indent=2))
    else:
        _print_human(results)
        if not overall:
            failed = [c.name for res in results for c in res.checks
                      if c.severity == "error" and not c.ok]
            print(f"FAILED checks: {failed}", file=sys.stderr)

    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
