#!/usr/bin/env python3
"""Re-do TTS + mux for all narration shots that failed TTS.

This script reads shots_state.json, identifies shots with narration_error,
re-runs tts.synth() with the now-correct VIDEOGEN_NARRATOR_TTS_MODEL,
then muxes the audio into the existing video clip.

Usage: python scripts/retts.py --project death_train --episode 001
"""
import json
import sys
from pathlib import Path

# Add src to path so we can import videogen modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from videogen import config as cfg
from videogen import ffmpeg as ff
from videogen import state
from videogen import tts as tts_mod
from videogen.storyboard import Storyboard


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--episode", required=True)
    args = ap.parse_args()

    ep_dir = state.episode_dir(args.project, args.episode)
    storyboard_path = ep_dir / "storyboard.json"
    shots_state_path = ep_dir / "shots_state.json"

    sb = Storyboard.model_validate_json(storyboard_path.read_text())
    ss = json.loads(shots_state_path.read_text())

    # Build shot lookup from storyboard (shots are on storyboard level, not scene)
    shot_map = {}
    for shot in sb.shots:
        shot_map[shot.id] = shot

    fixed = 0
    for sid, rec in ss.items():
        if rec.get("needs_director_rewrite"):
            continue

        shot = shot_map.get(sid)
        if not shot or shot.role != "narration" or not shot.narration_text:
            continue

        # Check winner attempt for TTS failure
        winner_ver = rec.get("winner_version")
        if not winner_ver:
            continue

        winner_attempt = None
        for att in rec.get("attempts", []):
            if att["version"] == winner_ver:
                winner_attempt = att
                break

        if not winner_attempt:
            continue

        # If TTS already succeeded, skip
        if winner_attempt.get("narration_audio_path") and not winner_attempt.get("narration_error"):
            print(f"  {sid}: TTS already OK, skip")
            continue

        # Re-run TTS + mux
        clip_path = Path(winner_attempt["clip_path"])
        audio_out = ep_dir / "audio" / f"{sid}-ver{winner_ver}.wav"
        raw_clip = ep_dir / "clips" / f"{sid}-ver{winner_ver}.raw.mp4"
        last_frame_path = Path(winner_attempt["last_frame_path"])

        voice = (
            shot.narrator_voice
            or sb.narrator_voice
            or None
        )

        print(f"  {sid}: TTS voice={voice}, text='{shot.narration_text[:30]}...'")
        try:
            # TTS
            audio_out.parent.mkdir(parents=True, exist_ok=True)
            tts_mod.synth(shot.narration_text, out_path=audio_out, voice=voice)

            a_dur = ff.probe_duration(audio_out)
            v_dur = ff.probe_duration(clip_path)
            print(f"  {sid}: TTS OK ({a_dur:.1f}s audio, {v_dur:.1f}s video)")

            # Mux: rename original to .raw.mp4, then mux audio in
            if clip_path.exists():
                if raw_clip.exists():
                    raw_clip.unlink()
                clip_path.rename(raw_clip)
            ff.mux_audio(raw_clip, audio_out, clip_path, fit="narration")

            # Re-extract last frame (video may be freeze-padded now)
            ff.extract_last_frame(clip_path, last_frame_path)

            # Update shots_state
            winner_attempt["narration_audio_path"] = str(audio_out)
            winner_attempt["narration_error"] = None
            winner_attempt["raw_clip_path"] = str(raw_clip)
            fixed += 1
            print(f"  {sid}: muxed OK")

        except Exception as e:
            print(f"  {sid}: TTS/mux FAILED: {e}")
            # Restore clip if we moved it
            if raw_clip.exists() and not clip_path.exists():
                raw_clip.rename(clip_path)

    # Write back shots_state
    shots_state_path.write_text(json.dumps(ss, indent=2, ensure_ascii=False))
    print(f"\nFixed {fixed} shots. shots_state.json updated.")


if __name__ == "__main__":
    main()