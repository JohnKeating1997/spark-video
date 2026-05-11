"""Narration TTS — qwen3-tts-flash voiceover synthesis.

Used by the narration-mode render pipeline (see ``render.py``) to turn
``Shot.narration_text`` into a wav file that ``ffmpeg.mux_audio`` then
splices onto the rendered clip in place of the original audio.

Single endpoint, single call, single output file. We deliberately keep
this **outside** the video provider abstraction (``providers/``) because:

  * TTS is not vendor-pluggable for this project — qwen3-tts-flash is
    the canonical narrator and matches the rest of the DashScope auth
    surface.
  * It runs as a *post-pass* on a rendered clip, so it doesn't need the
    submit/poll lifecycle the video providers share.

Endpoint reference: ``api-references/dashscope/tts/qwen-tts.md``.
"""
from __future__ import annotations

import time
from pathlib import Path

import httpx
from rich.console import Console
from tenacity import retry, stop_after_attempt, wait_exponential

from . import ffmpeg as ff, model_log
from .config import SETTINGS

console = Console()


def _is_cjk_char(ch: str) -> bool:
    o = ord(ch)
    return (
        0x4E00 <= o <= 0x9FFF
        or 0x3400 <= o <= 0x4DBF
        or 0x20000 <= o <= 0x2A6DF
        or 0x3000 <= o <= 0x303F  # CJK punctuation
    )


def estimate_narration_audio_seconds(
    text: str,
    *,
    speech_rate: float | None = None,
) -> float:
    """Heuristic wall-clock seconds for narration audio **after** ``speech_rate``.

    qwen3-tts does not return duration before synthesis; this is a soft
    budget check only. Tuned slightly pessimistic (may over-estimate) so
    ``storyboard validate`` is more likely to warn than to miss a
    freeze-frame tail.

    ``speech_rate`` defaults to ``SETTINGS.narrator_speech_rate`` (same as
    render-time ffmpeg ``atempo``).
    """
    rate = SETTINGS.narrator_speech_rate if speech_rate is None else speech_rate
    rate = max(0.05, float(rate))
    s = (text or "").strip()
    if not s:
        return 0.0
    cjk = sum(1 for ch in s if _is_cjk_char(ch))
    non_cjk = max(0, len(s) - cjk)
    # Natural-speed upper bound (seconds before atempo): ~3 chars/s CJK,
    # Latin+punct mix as slower per glyph than pure ASCII words.
    natural_sec = max(0.35, cjk / 3.0 + non_cjk / 12.0)
    return natural_sec / rate

TTS_PATH = "/services/aigc/multimodal-generation/generation"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
def _post(body: dict) -> dict:
    """One synchronous TTS call; retried on transient failure."""
    url = SETTINGS.base_url + TTS_PATH
    headers = {
        "Authorization": f"Bearer {SETTINGS.require_api_key()}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=60.0) as c:
        r = c.post(url, json=body, headers=headers)
        r.raise_for_status()
        return r.json()


def synth(
    text: str,
    *,
    out_path: Path,
    voice: str | None = None,
    language: str | None = None,
    model: str | None = None,
    speech_rate: float | None = None,
) -> Path:
    """Synthesize ``text`` into ``out_path`` (.wav). Returns ``out_path``.

    Voice / language / model fall back to env defaults when omitted:
    ``VIDEOGEN_NARRATOR_VOICE`` (default ``Cherry``),
    ``VIDEOGEN_NARRATOR_LANGUAGE`` (``Auto``),
    ``VIDEOGEN_NARRATOR_TTS_MODEL`` (``qwen3-tts-flash``).
    ``speech_rate`` defaults to ``VIDEOGEN_NARRATOR_SPEECH_RATE`` (default
    ``1.2``): post-process with ffmpeg ``atempo`` so wall-clock audio is
    shorter (short-form pacing). Set ``1.0`` to disable.

    Raises if ``text`` is empty or the upstream call fails after retries.
    Logs the request/response pair via ``model_log.log_call`` so it
    appears in ``logs/model_calls.jsonl`` next to the video calls.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("tts.synth: text is empty")

    voice = voice or SETTINGS.narrator_voice
    language = language or SETTINGS.narrator_language
    model = model or SETTINGS.narrator_tts_model
    tempo = SETTINGS.narrator_speech_rate if speech_rate is None else float(speech_rate)
    tempo = max(0.5, min(2.0, tempo))

    body: dict = {
        "model": model,
        "input": {"text": text, "voice": voice, "language_type": language},
    }

    url = SETTINGS.base_url + TTS_PATH
    t0 = time.time()
    data: dict | None = None
    err: str | None = None
    audio_url: str | None = None
    try:
        data = _post(body)
        if data.get("code"):
            raise RuntimeError(f"qwen-tts failed: {data}")
        audio_url = (data.get("output") or {}).get("audio", {}).get("url")
        if not audio_url:
            raise RuntimeError(f"qwen-tts response missing audio.url: {data}")
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        raise
    finally:
        model_log.log_call(
            kind="tts",
            provider="dashscope",
            model=model,
            endpoint=url,
            request=body,
            response=data,
            duration_ms=(time.time() - t0) * 1000,
            error=err,
            extra={
                "voice": voice,
                "language": language,
                "chars": len(text),
                "speech_rate": tempo,
            },
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw_wav = out_path.with_suffix(out_path.suffix + ".upstream.wav")
    try:
        ff.download(audio_url, raw_wav)
        ff.audio_atempo(raw_wav, out_path, tempo)
    finally:
        if raw_wav.exists():
            raw_wav.unlink(missing_ok=True)

    est = estimate_narration_audio_seconds(text, speech_rate=tempo)
    dur = ff.probe_duration(out_path)
    console.print(
        f"[green]✓ tts[/] {out_path.name} ({len(text)} chars, voice={voice}, "
        f"atempo={tempo:.2f}, ~{est:.1f}s est, {dur:.1f}s actual)"
    )
    return out_path
