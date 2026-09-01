# /// script
# requires-python = ">=3.10"
# dependencies = ["pydantic>=2.5", "httpx>=0.27", "rich>=13.0"]
# ///
"""
stitch.py — assemble the final mp4 from per-shot winning clips.

Pipeline:
    1. Read storyboard.json + shots_state.json
    2. For each shot in order, locate winner clip (clips/<id>.mp4)
    2b. If a continuation take (clips/<id>b.mp4 or clips/<id>b-ver*.mp4) is
        present, xfade-join it onto the main clip first — used when narration
        exceeds the provider's hard per-clip duration cap
    3. For narration shots: synthesize TTS via ./scripts/bl speech synthesize,
       strip the clip's audio, mux the TTS in (lib.ffmpeg_helpers.mux_audio)
    4. Concat all clips (with optional --crossfade)
    5. If storyboard.bgm is configured, mix in BGM track
    6. Normalize the assembled program audio and verify target duration

Output: projects/<p>/<ep>/final/<p>-<ep>.mp4
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from lib.env import load_pwd_dotenv                 # noqa: E402
from lib.storyboard import Storyboard       # noqa: E402
from lib.ffmpeg_helpers import (              # noqa: E402
    concat as concat_clips,
    mux_audio as mux_audio_to_video,
    mix_bgm,
    normalize_program_audio,
    probe_duration,
    strip_audio,
    audio_atempo,
    xfade_continuation,
)
from lib.bgm import resolve_track             # noqa: E402
from lib.cli import bl_cmd                    # noqa: E402

load_pwd_dotenv()


_CONTINUATION_XFADE_S = 1.0


def _find_continuation_clip(clips_dir: Path, shot_id: str) -> Path | None:
    """Return the producer-rendered continuation clip for ``shot_id`` if any.

    Convention: a "b" suffix sibling of the winner clip indicates a second
    take that should be xfade-joined with the main clip before narration
    muxing — used when narration is longer than a single take can cover under
    a model's hard duration cap (Wan3.0: 30s; legacy Wan2.7: 15s).

    Looks for ``<id>b.mp4`` first (promoted via ``--accept-version``); falls
    back to the highest-versioned ``<id>b-ver*.mp4`` so producers can simply
    leave the rendered file in place without promoting it.
    """
    promoted = clips_dir / f"{shot_id}b.mp4"
    if promoted.exists():
        return promoted
    versioned = sorted(clips_dir.glob(f"{shot_id}b-ver*.mp4"))
    return versioned[-1] if versioned else None


def _projects_root() -> Path:
    return Path(os.environ.get("VIDEOGEN_PROJECTS_DIR", "./projects")).resolve()


def _episode_dir() -> Path:
    proj = os.environ.get("SPARK_VIDEO_PROJECT")
    ep = os.environ.get("SPARK_VIDEO_EPISODE")
    if not proj or not ep:
        print("ERROR: SPARK_VIDEO_PROJECT and SPARK_VIDEO_EPISODE must be set",
              file=sys.stderr)
        sys.exit(2)
    ep_id = ep if ep.startswith("episode-") else f"episode-{ep}"
    return _projects_root() / proj / ep_id


def _synth_narration(
    text: str,
    out_wav: Path,
    voice: str,
    rate: float,
    model: str,
) -> None:
    """Call the platform-native bl wrapper for narration TTS."""
    try:
        bl_prefix = bl_cmd(_HERE.parent)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Narration TTS needs the optional bl CLI. Run "
            "the narration-aware doctor install plan, "
            "approve the bl install, then complete `bl auth login`."
        ) from exc
    auth = subprocess.run(
        bl_prefix + ["auth", "status"],
        capture_output=True,
        timeout=15,
        check=False,
    )
    if auth.returncode != 0:
        raise RuntimeError(
            "Narration TTS needs an authenticated bl CLI. Run `bl auth login`, "
            "then retry the narration-aware doctor check."
        )
    if not text.strip():
        raise RuntimeError("post-TTS shot has empty speech_text")
    cmd = bl_prefix + [
        "speech", "synthesize",
        "--text", text,
        "--voice", voice,
        "--rate", str(rate),
        "--out", str(out_wav),
    ]
    if model and not model.startswith("cosyvoice"):
        # qwen-tts fallback path — delegate to scripts/tts_qwen.py
        subprocess.run(
            ["uv", "run", str(_HERE / "tts_qwen.py"),
             "--text", text, "--out", str(out_wav),
             "--voice", voice, "--rate", str(rate), "--model", model],
            check=True,
        )
        return
    subprocess.run(cmd, check=True, timeout=120)


def _fit_tts_to_video(
    tts_wav: Path,
    video_clip: Path,
    *,
    max_tempo: float = 1.8,
    tolerance_s: float = 0.05,
) -> tuple[Path, float, float, float]:
    """Compress TTS via ffmpeg atempo so it fits inside the video clip.

    Implements the director SKILL's narration alignment rule:
        video shorter than narration → speed up narration via atempo to
        align with the clip and avoid frozen frames.

    Returns (final_wav_path, applied_tempo, audio_dur_before, video_dur).
    applied_tempo == 1.0 means audio already fit; the original wav is returned.
    When the required tempo exceeds max_tempo, applies max_tempo (a small tail
    freeze may remain — caller can warn).
    """
    v_dur = probe_duration(video_clip)
    a_dur = probe_duration(tts_wav)
    if v_dur <= 0 or a_dur <= 0:
        return tts_wav, 1.0, a_dur, v_dur
    if a_dur <= v_dur + tolerance_s:
        return tts_wav, 1.0, a_dur, v_dur
    tempo = min(max_tempo, a_dur / v_dur)
    dest = tts_wav.with_name(f"{tts_wav.stem}-fit.wav")
    audio_atempo(tts_wav, dest, tempo)
    return dest, tempo, a_dur, v_dur


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--crossfade", type=float, default=0.0,
                    help="seconds of crossfade between clips (0 = hard cut)")
    ap.add_argument("--out", default=None,
                    help="override output path (default: final/<p>-<ep>.mp4)")
    ap.add_argument("--allow-below-threshold", action="store_true",
                    help="include shots whose winner_version was a forced best-of-N")
    args = ap.parse_args()

    ep_dir = _episode_dir()
    sb = Storyboard.model_validate(json.loads((ep_dir / "storyboard.json").read_text()))
    state_path = ep_dir / "shots_state.json"
    if not state_path.exists():
        print("ERROR: shots_state.json not found — render first", file=sys.stderr)
        return 1
    state = json.loads(state_path.read_text())

    # Resolve voice / rate / TTS model from storyboard + env
    narrator_voice = sb.audio.voice or sb.narrator_voice or os.environ.get(
        "SPARK_VIDEO_NARRATOR_VOICE",
        os.environ.get("VIDEOGEN_NARRATOR_VOICE", "longanyang"),
    )
    narrator_rate = float(os.environ.get(
        "SPARK_VIDEO_NARRATOR_SPEECH_RATE",
        os.environ.get("VIDEOGEN_NARRATOR_SPEECH_RATE", "1.2"),
    ))
    narrator_model = os.environ.get(
        "SPARK_VIDEO_NARRATOR_TTS_MODEL",
        os.environ.get("VIDEOGEN_NARRATOR_TTS_MODEL", "cosyvoice-v3-flash"),
    )

    # Walk shots in storyboard order, locate winner clips, do per-shot
    # narration mux if needed
    with tempfile.TemporaryDirectory(prefix="spark-stitch-") as tmp:
        tmp_dir = Path(tmp)
        ordered_clips: list[Path] = []
        audio_entries: list[dict] = []
        for shot in sb.shots:
            entry = state.get(shot.id)
            if not entry or not entry.get("winner_version"):
                print(f"ERROR: shot {shot.id} has no winner_version", file=sys.stderr)
                return 1
            clip = ep_dir / "clips" / f"{shot.id}.mp4"
            if not clip.exists():
                print(f"ERROR: {clip} missing", file=sys.stderr)
                return 1

            # If the producer rendered a continuation take (long narration
            # spanning beyond the model's per-clip cap), xfade-join it onto
            # the main clip so downstream muxing sees a single source.
            cont = _find_continuation_clip(ep_dir / "clips", shot.id)
            if cont:
                joined = tmp_dir / f"{shot.id}-combined.mp4"
                xfade_continuation(clip, cont, joined,
                                   xfade_s=_CONTINUATION_XFADE_S)
                a_dur = probe_duration(clip)
                joined_dur = probe_duration(joined)
                print(f"[continuation] {shot.id}: a={a_dur:.2f}s + "
                      f"{cont.name} → combined={joined_dur:.2f}s "
                      f"(xfade={_CONTINUATION_XFADE_S:.1f}s)",
                      file=sys.stderr)
                clip = joined

            speech_source = shot.speech_source or (
                "post_tts" if shot.role == "narration" else "model"
            )
            speech_text = shot.speech_text or shot.narration_text or ""
            shot_voice = shot.narrator_voice or narrator_voice
            if speech_source == "post_tts":
                # 1. synthesize TTS
                tts_wav = tmp_dir / f"{shot.id}.wav"
                try:
                    _synth_narration(speech_text, tts_wav, shot_voice, narrator_rate,
                                     narrator_model)
                except Exception as e:
                    print(f"ERROR: TTS for {shot.id} failed: {e}", file=sys.stderr)
                    return 1
                # 1.5 retime TTS so it fits within the video (no frame freeze)
                tts_wav, tempo, a_dur, v_dur = _fit_tts_to_video(tts_wav, clip)
                if tempo > 1.0:
                    residual = max(0.0, (a_dur / tempo) - v_dur)
                    msg = (f"[fit] {shot.id}: a={a_dur:.2f}s v={v_dur:.2f}s "
                           f"→ atempo×{tempo:.3f}")
                    if residual > 0.05:
                        # Significant freeze tail remains even at max atempo.
                        # If the model's hard duration cap is reached,
                        # bumping shot.duration won't help; render
                        # a continuation take (<id>b.mp4) instead — stitch
                        # will xfade-join it automatically.
                        fix = ("render a continuation clip "
                               f"clips/{shot.id}b.mp4 (stitch will xfade-join)"
                               if not cont
                               else "even with the continuation take this "
                                    "shot is still under-budget — split into "
                                    "two storyboard shots")
                        msg += (f" (residual freeze ~{residual:.2f}s — "
                                f"{fix})")
                    print(msg, file=sys.stderr)
                # 2. mux into clip (replace audio, fit duration)
                muxed = tmp_dir / f"{shot.id}-muxed.mp4"
                mux_audio_to_video(
                    video=clip, audio=tts_wav, out=muxed,
                    fit="narration",
                )
                ordered_clips.append(muxed)
                audio_entries.append({
                    "shot_id": shot.id,
                    "speech_source": "post_tts",
                    "speaker": shot.speaker or sb.audio.presenter,
                    "voice": shot_voice,
                    "speech_text": speech_text,
                    "model_audio": "replaced",
                })
            elif sb.audio.model_audio_policy == "strip_all":
                silent = tmp_dir / f"{shot.id}-silent.mp4"
                strip_audio(clip, silent)
                ordered_clips.append(silent)
                audio_entries.append({
                    "shot_id": shot.id,
                    "speech_source": speech_source,
                    "speaker": shot.speaker,
                    "voice": None,
                    "speech_text": speech_text or None,
                    "model_audio": "stripped",
                })
            else:
                ordered_clips.append(clip)
                audio_entries.append({
                    "shot_id": shot.id,
                    "speech_source": speech_source,
                    "speaker": shot.speaker,
                    "voice": None,
                    "speech_text": speech_text or None,
                    "model_audio": "kept",
                })

        # Concat
        concat_out = tmp_dir / "concat.mp4"
        concat_clips(ordered_clips, concat_out, crossfade_s=args.crossfade)

        # BGM mix (if configured)
        final_video = concat_out
        if sb.bgm and sb.bgm.enabled and sb.bgm.mode != "off":
            tracks: dict[str, Path] = {}
            if sb.bgm.mode == "global" and sb.bgm.track:
                path = resolve_track(
                    project_id=os.environ["SPARK_VIDEO_PROJECT"],
                    episode_id=os.environ["SPARK_VIDEO_EPISODE"],
                    name=sb.bgm.track,
                )
                if path:
                    tracks["__global__"] = path
            # NOTE: scene-mode BGM (per-scene tracks switching mid-video) needs
            # additional segmenting work — left as a TODO; common case is global.
            if tracks:
                bgm_out = tmp_dir / "with-bgm.mp4"
                mix_bgm(
                    video=concat_out,
                    bgm=next(iter(tracks.values())),
                    out=bgm_out,
                    fade_in_s=sb.bgm.fade_in_s,
                    fade_out_s=sb.bgm.fade_out_s,
                )
                final_video = bgm_out

        # Apply one program-level loudness pass after narration, source audio,
        # and optional BGM have been assembled.  Per-clip normalization cannot
        # guarantee a stable final mix once those layers are combined.
        normalized_out = tmp_dir / "program-normalized.mp4"
        normalize_program_audio(final_video, normalized_out)
        final_video = normalized_out

        # Move to final/
        out_path = (Path(args.out) if args.out
                    else ep_dir / "final" /
                         f"{os.environ['SPARK_VIDEO_PROJECT']}-"
                         f"{os.environ['SPARK_VIDEO_EPISODE']}.mp4")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(final_video, out_path)

        audio_manifest = {
            "mode": sb.audio.mode,
            "presenter": sb.audio.presenter,
            "voice": sb.audio.voice,
            "model_audio_policy": sb.audio.model_audio_policy,
            "subtitle_mode": sb.audio.subtitle_mode,
            "shots": audio_entries,
        }
        audio_manifest_path = out_path.parent / "audio_manifest.json"
        audio_manifest_path.write_text(
            json.dumps(audio_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        duration = probe_duration(out_path)
        target_duration = float(sb.target_duration_s)
        duration_tolerance = max(3.0, target_duration * 0.05)
        duration_ok = (
            duration > 0
            and abs(duration - target_duration) <= duration_tolerance
        )
        print(json.dumps({
            "final_path": str(out_path),
            "duration_s": duration,
            "target_duration_s": target_duration,
            "duration_tolerance_s": duration_tolerance,
            "duration_ok": duration_ok,
            "audio_manifest": str(audio_manifest_path),
            "shots_count": len(sb.shots),
            "size_bytes": out_path.stat().st_size,
        }, ensure_ascii=False))

        # Build viewer.html + auto-open. Best-effort: never fail stitch.
        try:
            subprocess.run(
                ["uv", "run", str(_HERE / "build_viewer.py")],
                check=False,
            )
        except Exception as e:
            print(f"[viewer] skipped: {e}", file=sys.stderr)

        if not duration_ok:
            print(
                "ERROR: final duration is outside the storyboard budget "
                f"(actual={duration:.2f}s, target={target_duration:.2f}s, "
                f"tolerance=±{duration_tolerance:.2f}s)",
                file=sys.stderr,
            )
            return 1
        return 0


if __name__ == "__main__":
    sys.exit(main())
