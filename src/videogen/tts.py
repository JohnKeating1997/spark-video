"""Narration TTS — pluggable backends (CosyVoice default, Qwen-TTS legacy).

Used by the narration-mode render pipeline (see ``render.py``) to turn
``Shot.narration_text`` into a wav file that ``ffmpeg.mux_audio`` then
splices onto the rendered clip in place of the original audio.

Two upstream backends are supported; the public :func:`synth` dispatches
by ``model`` name prefix:

* ``cosyvoice-*`` *(default)* — ``POST /services/audio/tts/SpeechSynthesizer``.
  Native ``rate`` field controls speed at synthesis time (no extra
  re-encode). Supports system voices like ``longanyang`` / ``longwan``
  and custom-cloned voices. **北京地域专属** — when ``VIDEOGEN_REGION``
  is set to ``singapore`` this backend is unavailable and a clear error
  is raised so the caller can fall back to ``qwen3-tts-flash``.
  Endpoint reference: ``api-references/dashscope/tts/cosyvoice-tts.md``.

* ``qwen*-tts*`` — ``POST /services/aigc/multimodal-generation/generation``.
  No native rate control; we post-process with ffmpeg ``atempo``. Voices
  are CamelCase (``Cherry`` / ``Ethan`` / …).
  Endpoint reference: ``api-references/dashscope/tts/qwen-tts.md``.

Single endpoint per call, single output ``.wav`` file. We deliberately
keep TTS **outside** the video provider abstraction (``providers/``)
because it runs as a post-pass on a rendered clip and shares no
lifecycle with the video submit/poll loop.
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


# CosyVoice ``language_hints`` taxonomy (cosyvoice-tts.md):
#   zh / en / fr / de / ja / ko / ru / pt / th / id / vi
# Mapping from the qwen-tts ``language_type`` vocabulary we already
# expose via ``VIDEOGEN_NARRATOR_LANGUAGE``. Any value not in this
# table (e.g. ``Italian`` / ``Spanish``) is silently omitted on the
# cosyvoice backend — the model will then auto-detect.
_COSYVOICE_LANG_MAP: dict[str, str] = {
    "chinese": "zh",
    "english": "en",
    "french": "fr",
    "german": "de",
    "japanese": "ja",
    "korean": "ko",
    "russian": "ru",
    "portuguese": "pt",
    "thai": "th",
    "indonesian": "id",
    "vietnamese": "vi",
}


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

    DashScope TTS does not return duration before synthesis; this is a
    soft budget check only. Tuned slightly pessimistic (may over-estimate)
    so ``storyboard validate`` is more likely to warn than to miss a
    freeze-frame tail.

    ``speech_rate`` defaults to ``SETTINGS.narrator_speech_rate``. The
    result is the same regardless of backend: cosyvoice consumes the
    rate natively, qwen-tts applies it via ffmpeg ``atempo`` — both
    shrink wall-clock duration by ~the same factor.
    """
    rate = SETTINGS.narrator_speech_rate if speech_rate is None else speech_rate
    rate = max(0.05, float(rate))
    s = (text or "").strip()
    if not s:
        return 0.0
    cjk = sum(1 for ch in s if _is_cjk_char(ch))
    non_cjk = max(0, len(s) - cjk)
    # Natural-speed upper bound (seconds before rate adjustment):
    # ~3 chars/s CJK; Latin+punct mix is slower per glyph than pure ASCII.
    natural_sec = max(0.35, cjk / 3.0 + non_cjk / 12.0)
    return natural_sec / rate


# Backend selection by model name prefix.
QWEN_TTS_PATH = "/services/aigc/multimodal-generation/generation"
COSYVOICE_TTS_PATH = "/services/audio/tts/SpeechSynthesizer"


def _is_cosyvoice_model(model: str) -> bool:
    return model.lower().startswith("cosyvoice")


def _is_qwen_tts_model(model: str) -> bool:
    m = model.lower()
    return m.startswith("qwen") and "tts" in m


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
def _post(url: str, body: dict) -> dict:
    """One synchronous TTS call; retried on transient failure."""
    headers = {
        "Authorization": f"Bearer {SETTINGS.require_api_key()}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=60.0) as c:
        r = c.post(url, json=body, headers=headers)
        r.raise_for_status()
        return r.json()


def _synth_qwen(
    *,
    text: str,
    voice: str,
    language: str,
    model: str,
    tempo: float,
    out_path: Path,
) -> tuple[str, dict, dict]:
    """Run the qwen-tts backend. Returns (audio_url, request_body, response_json)."""
    body: dict = {
        "model": model,
        "input": {"text": text, "voice": voice, "language_type": language},
    }
    url = SETTINGS.base_url + QWEN_TTS_PATH
    data = _post(url, body)
    if data.get("code"):
        raise RuntimeError(f"qwen-tts failed: {data}")
    audio_url = (data.get("output") or {}).get("audio", {}).get("url")
    if not audio_url:
        raise RuntimeError(f"qwen-tts response missing audio.url: {data}")

    # qwen-tts has no native speed knob — post-process with ffmpeg atempo.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw_wav = out_path.with_suffix(out_path.suffix + ".upstream.wav")
    try:
        ff.download(audio_url, raw_wav)
        ff.audio_atempo(raw_wav, out_path, tempo)
    finally:
        if raw_wav.exists():
            raw_wav.unlink(missing_ok=True)

    return audio_url, body, data


def _synth_cosyvoice(
    *,
    text: str,
    voice: str,
    language: str,
    model: str,
    tempo: float,
    out_path: Path,
) -> tuple[str, dict, dict]:
    """Run the cosyvoice backend. Returns (audio_url, request_body, response_json).

    CosyVoice has a native ``rate`` parameter (0.5–2.0) that controls
    speech speed at synthesis time, so we skip the ffmpeg ``atempo``
    pass. ``language`` ("Auto"/"Chinese"/…) is mapped to cosyvoice's
    short codes (zh/en/…); unmapped values fall back to auto-detect.
    """
    if SETTINGS.region == "singapore":
        raise RuntimeError(
            "cosyvoice TTS is only available in the 北京 region "
            "(VIDEOGEN_REGION=beijing). Either switch region or set "
            "VIDEOGEN_NARRATOR_TTS_MODEL=qwen3-tts-flash."
        )

    input_obj: dict = {
        "text": text,
        "voice": voice,
        "format": "wav",
        "sample_rate": 24000,
        # Clamp into cosyvoice's accepted range and apply at synthesis time.
        "rate": max(0.5, min(2.0, float(tempo))),
    }
    code = _COSYVOICE_LANG_MAP.get((language or "").strip().lower())
    if code:
        input_obj["language_hints"] = [code]

    body: dict = {"model": model, "input": input_obj}
    url = SETTINGS.base_url + COSYVOICE_TTS_PATH
    data = _post(url, body)
    if data.get("code"):
        raise RuntimeError(f"cosyvoice failed: {data}")
    audio_url = (data.get("output") or {}).get("audio", {}).get("url")
    if not audio_url:
        raise RuntimeError(f"cosyvoice response missing audio.url: {data}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ff.download(audio_url, out_path)
    return audio_url, body, data


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
    ``VIDEOGEN_NARRATOR_VOICE``,
    ``VIDEOGEN_NARRATOR_LANGUAGE`` (``Auto``),
    ``VIDEOGEN_NARRATOR_TTS_MODEL`` (default ``cosyvoice-v3-flash``).

    Backend is picked by model name prefix:

    * ``cosyvoice-*`` — native ``rate`` is consumed by the API; no
      ffmpeg re-encode. Voices are e.g. ``longanyang`` / ``longwan``.
    * ``qwen*-tts*`` — wav is post-processed with ffmpeg ``atempo`` to
      apply ``speech_rate``. Voices are CamelCase ``Cherry`` / ``Ethan``.

    ``speech_rate`` defaults to ``VIDEOGEN_NARRATOR_SPEECH_RATE`` (1.2):
    wall-clock audio ends up shorter (short-form pacing). Set ``1.0`` to
    disable any speedup. Clamped to [0.5, 2.0] before being sent to the
    backend.

    Raises if ``text`` is empty, the model name belongs to no known
    backend, or the upstream call fails after retries. Logs the
    request/response pair via ``model_log.log_call`` so it appears in
    ``logs/model_calls.jsonl`` next to the video calls.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("tts.synth: text is empty")

    voice = voice or SETTINGS.narrator_voice
    language = language or SETTINGS.narrator_language
    model = model or SETTINGS.narrator_tts_model
    tempo = SETTINGS.narrator_speech_rate if speech_rate is None else float(speech_rate)
    tempo = max(0.5, min(2.0, tempo))

    if _is_cosyvoice_model(model):
        backend = "cosyvoice"
        runner = _synth_cosyvoice
        url = SETTINGS.base_url + COSYVOICE_TTS_PATH
    elif _is_qwen_tts_model(model):
        backend = "qwen-tts"
        runner = _synth_qwen
        url = SETTINGS.base_url + QWEN_TTS_PATH
    else:
        raise ValueError(
            f"tts.synth: cannot infer backend from model {model!r}. "
            f"Expected name starting with 'cosyvoice-' or 'qwen*-tts*'. "
            f"Set VIDEOGEN_NARRATOR_TTS_MODEL to one of the supported families."
        )

    t0 = time.time()
    body: dict | None = None
    data: dict | None = None
    err: str | None = None
    audio_url: str | None = None
    try:
        audio_url, body, data = runner(
            text=text,
            voice=voice,
            language=language,
            model=model,
            tempo=tempo,
            out_path=out_path,
        )
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
                "backend": backend,
                "voice": voice,
                "language": language,
                "chars": len(text),
                "speech_rate": tempo,
                "audio_url": audio_url,
            },
        )

    est = estimate_narration_audio_seconds(text, speech_rate=tempo)
    dur = ff.probe_duration(out_path)
    console.print(
        f"[green]✓ tts[/] {out_path.name} ({len(text)} chars, "
        f"backend={backend}, voice={voice}, rate={tempo:.2f}, "
        f"~{est:.1f}s est, {dur:.1f}s actual)"
    )
    return out_path
