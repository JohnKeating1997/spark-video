"""ffmpeg helpers for frame extraction, concat, downloads, audio mux."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Literal

import httpx
from rich.console import Console

console = Console()


def _ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found in PATH. Install via `brew install ffmpeg`.")


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=300.0, follow_redirects=True) as c, dest.open("wb") as f:
        with c.stream("GET", url) as r:
            r.raise_for_status()
            for chunk in r.iter_bytes(chunk_size=1 << 20):
                f.write(chunk)
    return dest


def extract_last_frame(video: Path, out: Path) -> Path:
    """Extract the very last frame as PNG. Used as next clip's first_frame."""
    _ensure_ffmpeg()
    out.parent.mkdir(parents=True, exist_ok=True)
    # Get total frame count first
    probe_cmd = [
        "ffprobe", "-v", "error", "-count_frames",
        "-select_streams", "v:0",
        "-show_entries", "stream=nb_read_frames",
        "-of", "csv=p=0", str(video),
    ]
    r = subprocess.run(probe_cmd, capture_output=True, text=True)
    nb_frames = int(r.stdout.strip()) - 1  # last frame index
    if nb_frames < 0:
        nb_frames = 0
    # Use select filter to grab the exact last frame
    cmd = [
        "ffmpeg", "-y", "-i", str(video),
        "-vf", f"select='eq(n\\,{nb_frames})'",
        "-vsync", "vfr", "-vframes", "1", "-q:v", "2", str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    if not out.exists() or out.stat().st_size == 0:
        # Fallback: try -sseof with larger offset
        cmd2 = [
            "ffmpeg", "-y", "-sseof", "-0.5", "-i", str(video),
            "-vframes", "1", "-q:v", "2", str(out),
        ]
        subprocess.run(cmd2, check=False, capture_output=True)
    return out


def extract_first_frame(video: Path, out: Path) -> Path:
    _ensure_ffmpeg()
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(video),
        "-vframes", "1", "-q:v", "2", str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def probe_duration(media: Path) -> float:
    """Return media duration in seconds via ffprobe. 0.0 if unknown."""
    _ensure_ffmpeg()
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0", str(media),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def audio_atempo(src: Path, dest: Path, tempo: float) -> Path:
    """Resample playback speed with FFmpeg ``atempo`` (0.5–2.0 per filter).

    ``tempo`` > 1.0 shortens wall-clock duration (faster speech). When
    ``tempo`` is ~1.0, copies ``src`` to ``dest`` without re-encode.
    """
    _ensure_ffmpeg()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if abs(tempo - 1.0) < 0.001:
        shutil.copy2(src, dest)
        return dest
    if not (0.5 <= tempo <= 2.0):
        raise ValueError(f"audio_atempo: tempo must be in [0.5, 2.0], got {tempo}")
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-filter:a", f"atempo={tempo:.6f}",
        "-vn", str(dest),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"ffmpeg audio_atempo failed (rc={r.returncode}):\n"
            f"  stderr tail: {r.stderr[-800:]}"
        )
    return dest


def _has_audio_stream(video: Path) -> bool:
    """Return True if the video file contains at least one audio stream."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0", str(video),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return r.stdout.strip() != ""


def _normalize_audio(video: Path, out: Path, *, ar: int = 24000, ac: int = 2) -> Path:
    """Ensure every clip has a video + AAC audio stream before concat.

    ffmpeg's concat demuxer with ``-c copy`` requires homogeneous stream
    layouts across all clips.  This function re-encodes every clip so it
    has exactly:

    - video: libx264 / yuv420p
    - audio: AAC 192k, ``ar`` Hz, ``ac`` channels

    Clips without an audio stream get a silent AAC track added
    (``-f lavfi -i anullsrc``) padded to match the video duration.
    Clips with mono audio are upmixed to ``ac`` channels.

    Defaults (ar=24000, ac=2) match DashScope video model output params.

    Returns the normalized clip path.
    """
    _ensure_ffmpeg()
    out.parent.mkdir(parents=True, exist_ok=True)
    v_dur = probe_duration(video)
    if v_dur <= 0:
        # Cannot probe duration — just copy and hope it's fine.
        shutil.copy2(video, out)
        return out

    if _has_audio_stream(video):
        # Re-encode to ensure consistent codec params (AAC 192k, same
        # sample rate and channel layout).  ffmpeg automatically upmixes
        # mono→stereo when -ac 2 is specified.
        cmd = [
            "ffmpeg", "-y", "-i", str(video),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-ar", str(ar), "-ac", str(ac),
            "-movflags", "+faststart",
            str(out),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(
                f"ffmpeg _normalize_audio (re-encode) failed (rc={r.returncode}):\n"
                f"  stderr tail: {r.stderr[-800:]}"
            )
    else:
        # No audio stream — add a silent AAC track padded to video length.
        # Use same sample rate and channel layout as the target to avoid
        # pops/clicks at boundaries with real audio clips.
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video),
            "-f", "lavfi", "-i", f"anullsrc=r={ar}:cl={('stereo' if ac == 2 else 'mono')}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-ar", str(ar), "-ac", str(ac),
            "-shortest",
            "-movflags", "+faststart",
            str(out),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(
                f"ffmpeg _normalize_audio (add silent) failed (rc={r.returncode}):\n"
                f"  stderr tail: {r.stderr[-800:]}"
            )
    return out


def strip_audio(video: Path, out: Path) -> Path:
    """Remove all audio streams from a video, producing a silent clip.

    Re-encodes with libx264 to ensure consistent output format.
    Used in narration mode to strip model-generated ambient noise
    from drama/dialogue shots that lack character voice audio.
    """
    _ensure_ffmpeg()
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(video),
        "-an",  # drop all audio
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"ffmpeg strip_audio failed (rc={r.returncode}):\n"
            f"  stderr tail: {r.stderr[-800:]}"
        )
    return out


def mux_audio(
    video: Path,
    audio: Path,
    out: Path,
    *,
    fit: Literal["audio", "video", "narration"] = "audio",
) -> Path:
    """Drop the video's original audio, replace it with ``audio``.

    ``fit`` controls how the two timelines are reconciled:

    * ``audio``: final clip length == audio length.
      If audio is longer than video → freeze the video's last frame for
      the gap (``tpad=stop_mode=clone``). If audio is shorter → trim
      the video to the audio length.

    * ``narration`` (旁白模式默认): final length is ``audio`` plus up to
      1 s of trailing picture when the source video is longer — the tail
      is silent so the beat gets a brief pause. If audio runs longer than
      video, freeze at most 1 s then trim excess audio so the clip never
      exceeds ``video + 1 s`` of hold-frame.

    * ``video``: final clip length == video length. Audio is padded with
      silence (``apad``) or trimmed to match.

    Always re-encodes (libx264 + aac) — ``-c copy`` cannot satisfy the
    pad/trim semantics. Output is mp4 with AAC audio.
    """
    _ensure_ffmpeg()
    out.parent.mkdir(parents=True, exist_ok=True)

    v_dur = probe_duration(video)
    a_dur = probe_duration(audio)
    if v_dur <= 0 or a_dur <= 0:
        raise RuntimeError(
            f"mux_audio: cannot probe durations (video={v_dur}s, audio={a_dur}s)"
        )

    _NARRATION_TAIL_S = 1.0

    if fit == "narration":
        target = min(max(a_dur, v_dur), a_dur + _NARRATION_TAIL_S)
        v_pad = target - v_dur
        a_pad = target - a_dur
        vf = (
            f"tpad=stop_mode=clone:stop_duration={v_pad:.3f}"
            if v_pad > 0.05
            else "null"
        )
        af = (
            f"apad=pad_dur={a_pad:.3f}"
            if a_pad > 0.05
            else "anull"
        )
    elif fit == "audio":
        target = a_dur
        delta = a_dur - v_dur
        if delta > 0.05:
            # Audio longer → freeze last frame to cover the tail.
            vf = f"tpad=stop_mode=clone:stop_duration={delta:.3f}"
        else:
            vf = "null"
        af = "anull"
    else:
        target = v_dur
        # Pad audio with silence if shorter; ffmpeg trims when longer via -t.
        vf = "null"
        af = "apad"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(audio),
        "-filter_complex",
        f"[0:v]{vf}[v];[1:a]{af}[a]",
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-ar", "24000", "-ac", "2",
        "-t", f"{target:.3f}",
        "-movflags", "+faststart",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"ffmpeg mux_audio failed (rc={r.returncode}):\n"
            f"  stderr tail: {r.stderr[-800:]}"
        )
    return out


def mix_bgm(
    video: Path,
    bgm: Path,
    out: Path,
    *,
    voice_lufs: float = -16.0,
    bgm_delta_lu: float = -14.0,
    fade_in_s: float = 0.5,
    fade_out_s: float = 1.0,
) -> Path:
    """Mix a BGM audio file underneath the existing audio of ``video``.

    Uses EBU R128 ``loudnorm`` to guarantee consistent relative levels
    regardless of input loudness:

    - Voice / narration / dialog is normalized to ``voice_lufs`` LUFS
      (broadcast standard: -16 LUFS for streaming content).
    - BGM is normalized to ``voice_lufs + bgm_delta_lu`` LUFS, i.e. a
      fixed offset below the voice. Default ``bgm_delta_lu = -14`` means
      BGM targets -30 LUFS — comfortably underneath speech without
      competing for attention.

    The BGM loops (if shorter) or trims (if longer) to match the video
    duration, then crossfades in/out. ``amix`` with ``duration=first``
    ensures the final clip length matches the video exactly.

    If the input video has no audio stream, a silent track is created
    on the fly and the BGM becomes the sole audio (normalized to
    ``voice_lufs`` since there is no voice to duck under).

    Always re-encodes (aac for audio; video is ``-c:v copy`` unless that
    fails, then falls back to libx264 re-encode). Output is mp4.
    """
    _ensure_ffmpeg()
    out.parent.mkdir(parents=True, exist_ok=True)
    if not bgm.exists():
        raise FileNotFoundError(f"mix_bgm: bgm file not found: {bgm}")

    v_dur = probe_duration(video)
    if v_dur <= 0:
        raise RuntimeError(f"mix_bgm: cannot probe video duration: {video}")

    bgm_target = voice_lufs + bgm_delta_lu
    fade_in = max(0.0, float(fade_in_s))
    fade_out = max(0.0, float(fade_out_s))
    fade_out_start = max(0.0, v_dur - fade_out)

    # Voice chain: normalize to voice_lufs using EBU R128 loudnorm.
    # TP=-1.5 prevents true peaks above -1.5 dBFS; LRA=11 limits range.
    voice_chain = (
        f"[0:a]loudnorm=I={voice_lufs:.1f}:TP=-1.5:LRA=11[voice]"
    )

    # BGM chain: loop → trim → normalize to bgm_target → fade in/out.
    bgm_chain = (
        f"[1:a]aloop=loop=-1:size=2e9,"
        f"atrim=0:{v_dur:.3f},asetpts=PTS-STARTPTS,"
        f"loudnorm=I={bgm_target:.1f}:TP=-1.5:LRA=6,"
        f"afade=t=in:st=0:d={fade_in:.3f},"
        f"afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}"
        f"[bgm]"
    )

    has_audio = _has_audio_stream(video)
    if has_audio:
        filt = (
            f"{voice_chain};"
            f"{bgm_chain};"
            f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
        inputs = ["-i", str(video), "-i", str(bgm)]
    else:
        # No source audio — BGM becomes the sole audio, normalized to
        # voice_lufs (no ducking needed).
        bgm_solo_chain = (
            f"[1:a]aloop=loop=-1:size=2e9,"
            f"atrim=0:{v_dur:.3f},asetpts=PTS-STARTPTS,"
            f"loudnorm=I={voice_lufs:.1f}:TP=-1.5:LRA=6,"
            f"afade=t=in:st=0:d={fade_in:.3f},"
            f"afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}"
            f"[bgm]"
        )
        filt = bgm_solo_chain
        inputs = ["-i", str(video), "-i", str(bgm)]
        # Map BGM directly as output audio.
        cmd = [
            "ffmpeg", "-y", *inputs,
            "-filter_complex", filt,
            "-map", "0:v", "-map", "[bgm]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-ar", "24000", "-ac", "2",
            "-shortest",
            "-movflags", "+faststart",
            str(out),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            cmd_reenc = list(cmd)
            idx = cmd_reenc.index("-c:v")
            cmd_reenc[idx + 1] = "libx264"
            cmd_reenc.insert(idx + 2, "-pix_fmt")
            cmd_reenc.insert(idx + 3, "yuv420p")
            r2 = subprocess.run(cmd_reenc, capture_output=True, text=True)
            if r2.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg mix_bgm (no audio) failed:\n"
                    f"  stderr tail: {r2.stderr[-400:]}"
                )
        return out

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filt,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-ar", "24000", "-ac", "2",
        "-shortest",
        "-movflags", "+faststart",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        # ``-c:v copy`` can fail when the source isn't mp4-friendly; retry
        # with a re-encode pass so we always succeed on weird inputs.
        cmd_reenc = list(cmd)
        idx = cmd_reenc.index("-c:v")
        cmd_reenc[idx + 1] = "libx264"
        cmd_reenc.insert(idx + 2, "-pix_fmt")
        cmd_reenc.insert(idx + 3, "yuv420p")
        r2 = subprocess.run(cmd_reenc, capture_output=True, text=True)
        if r2.returncode != 0:
            raise RuntimeError(
                f"ffmpeg mix_bgm failed (rc={r2.returncode}):\n"
                f"  first attempt stderr tail: {r.stderr[-400:]}\n"
                f"  re-encode stderr tail: {r2.stderr[-400:]}"
            )
    return out


def concat(clips: list[Path], out: Path, *, crossfade_s: float = 0.0) -> Path:
    """Concatenate clips. If crossfade_s > 0, applies xfade between each pair.

    For MVP we use the simple concat demuxer (no crossfade, no re-encode).
    Crossfade path falls back to filter_complex re-encode.
    """
    _ensure_ffmpeg()
    out.parent.mkdir(parents=True, exist_ok=True)
    if not clips:
        raise ValueError("no clips to concat")

    if crossfade_s <= 0:
        # Normalize audio streams so concat demuxer doesn't break on
        # clips with different stream layouts (audio-less vs AAC-muxed).
        norm_dir = out.parent / "_normalize_tmp"
        norm_dir.mkdir(parents=True, exist_ok=True)
        norm_clips: list[Path] = []
        for c in clips:
            norm_path = norm_dir / c.name
            _normalize_audio(c, norm_path)
            norm_clips.append(norm_path)

        listfile = out.with_suffix(".txt")
        listfile.write_text("\n".join(f"file '{c.resolve()}'" for c in norm_clips), encoding="utf-8")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(listfile), "-c", "copy", str(out),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        # Clean up temp normalized clips regardless of success/failure.
        for p in norm_dir.iterdir():
            p.unlink(missing_ok=True)
        norm_dir.rmdir()
        if r.returncode != 0:
            raise RuntimeError(
                f"ffmpeg concat failed (rc={r.returncode}):\n"
                f"  stderr tail: {r.stderr[-800:]}"
            )
        return out

    # crossfade path — re-encodes; normalize audio first for same reason.
    norm_dir = out.parent / "_normalize_tmp"
    norm_dir.mkdir(parents=True, exist_ok=True)
    norm_clips: list[Path] = []
    for c in clips:
        norm_path = norm_dir / c.name
        _normalize_audio(c, norm_path)
        norm_clips.append(norm_path)

    inputs: list[str] = []
    for c in norm_clips:
        inputs += ["-i", str(c)]
    n = len(norm_clips)
    filt_parts = []
    last = "[0:v]"
    last_a = "[0:a]"
    offset = 0.0
    # Naive cumulative xfade. Caller should keep clips short to avoid drift.
    for i in range(1, n):
        offset += 8.0 - crossfade_s  # assumes ~8s clips; tune in caller
        filt_parts.append(
            f"{last}[{i}:v]xfade=transition=fade:duration={crossfade_s}:offset={offset:.2f}[v{i}]"
        )
        filt_parts.append(
            f"{last_a}[{i}:a]acrossfade=d={crossfade_s}[a{i}]"
        )
        last = f"[v{i}]"
        last_a = f"[a{i}]"
    filt = ";".join(filt_parts)
    cmd = [
        "ffmpeg", "-y", *inputs, "-filter_complex", filt,
        "-map", last, "-map", last_a,
        "-c:v", "libx264", "-c:a", "aac", str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    # Clean up temp normalized clips.
    for p in norm_dir.iterdir():
        p.unlink(missing_ok=True)
    norm_dir.rmdir()
    return out
