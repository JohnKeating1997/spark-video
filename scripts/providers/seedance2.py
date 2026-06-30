# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.31"]
# ///
"""
Ark Seedance 2.0 provider.

Uses Volcengine Ark's async content generation API:
    POST /api/v3/contents/generations/tasks
    GET  /api/v3/contents/generations/tasks/{task_id}

Local image references are encoded as data:image/... URLs, which Ark accepts
for image_url.url. Local video/audio files are intentionally rejected: upload
them to Ark assets or provide an http(s):// / asset:// URL.

Public API:
    render(kind, prompt, media, voice, duration, out_path, extra) -> dict
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import requests


ARK_BASE = (
    os.environ.get("ARK_BASE_URL")
    or os.environ.get("SEEDANCE2_BASE_URL")
    or "https://ark.cn-beijing.volces.com/api/v3"
).rstrip("/")
API_KEY = os.environ.get("ARK_API_KEY") or os.environ.get("VOLCENGINE_API_KEY")
DEFAULT_MODEL = os.environ.get("SEEDANCE2_MODEL") or "doubao-seedance-2-0-260128"

_REMOTE_PREFIXES = ("http://", "https://", "asset://", "data:")
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
_SUCCESS_STATUSES = {"succeeded", "success", "completed"}
_FAILED_STATUSES = {"failed", "canceled", "cancelled", "expired"}
_LOG_MAX_STR = 8000


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _headers() -> dict[str, str]:
    if not API_KEY:
        raise RuntimeError("ARK_API_KEY is not set; seedance2 provider needs it.")
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }


def _is_remote_ref(value: str) -> bool:
    return value.startswith(_REMOTE_PREFIXES)


def _suffix_for(ref: str | Path) -> str:
    if isinstance(ref, Path):
        return ref.suffix.lower()
    if ref.startswith("data:"):
        mime = ref.split(";", 1)[0].removeprefix("data:").lower()
        return {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "video/mp4": ".mp4",
            "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3",
            "audio/wav": ".wav",
        }.get(mime, "")
    if ref.startswith(("http://", "https://")):
        return Path(urlparse(ref).path).suffix.lower()
    return ""


def _media_type_for(ref: str | Path, *, default: str = "image") -> str:
    suffix = _suffix_for(ref)
    if suffix in _IMAGE_EXTS:
        return "image"
    if suffix in _VIDEO_EXTS:
        return "video"
    if suffix in _AUDIO_EXTS:
        return "audio"
    return default


def _image_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in _IMAGE_EXTS:
        raise ValueError(
            f"seedance2 local references only support images; got {path}"
        )
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _ref_url(ref: str | Path, *, expected: str) -> str:
    if isinstance(ref, str) and _is_remote_ref(ref):
        return ref
    path = Path(ref).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"media file not found: {path}")
    if expected == "image":
        return _image_data_url(path)
    raise ValueError(
        "seedance2 only auto-embeds local image files. "
        f"Upload local {expected} files to Ark assets or pass an http(s):// "
        f"/ asset:// URL: {path}"
    )


def _content_item(media_type: str, url: str, role: str) -> dict[str, Any]:
    key = f"{media_type}_url"
    return {
        "type": key,
        key: {"url": url},
        "role": role,
    }


def _normalise_resolution(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("P"):
        text = text[:-1] + "p"
    if text.endswith("K"):
        text = text[:-1] + "k"
    return text


def _build_content(
    *,
    kind: str,
    prompt: str,
    media: list[str | Path],
    voice: str | Path | None,
    extra: dict[str, Any],
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    first_frame = extra.get("first_frame_url")

    if kind == "t2v":
        pass
    elif kind == "i2v":
        ref = first_frame or (media[0] if media else None)
        if not ref:
            raise ValueError("i2v requires media[0] or --first-frame")
        content.append(
            _content_item("image", _ref_url(ref, expected="image"), "first_frame")
        )
    elif kind == "r2v":
        image_items: list[dict[str, Any]] = []
        video_items: list[dict[str, Any]] = []
        audio_items: list[dict[str, Any]] = []

        if first_frame:
            role = os.environ.get("SEEDANCE2_FIRST_FRAME_ROLE", "first_frame").strip()
            image_items.append(
                _content_item("image", _ref_url(first_frame, expected="image"), role)
            )

        for ref in media:
            media_type = _media_type_for(ref, default="image")
            role = {
                "image": "reference_image",
                "video": "reference_video",
                "audio": "reference_audio",
            }[media_type]
            item = _content_item(
                media_type,
                _ref_url(ref, expected=media_type),
                role,
            )
            if media_type == "image":
                image_items.append(item)
            elif media_type == "video":
                video_items.append(item)
            else:
                audio_items.append(item)

        if voice is not None:
            audio_items.append(
                _content_item(
                    "audio",
                    _ref_url(voice, expected="audio"),
                    "reference_audio",
                )
            )

        content.extend(image_items)
        content.extend(video_items)
        content.extend(audio_items)
    else:
        raise ValueError(f"unknown kind: {kind}")

    return content


def _truncate_for_log(obj: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "<truncated:depth>"
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in {"authorization", "api_key"}:
                out[k] = "<redacted>"
            else:
                out[k] = _truncate_for_log(v, depth=depth + 1)
        return out
    if isinstance(obj, list):
        return [_truncate_for_log(v, depth=depth + 1) for v in obj]
    if isinstance(obj, str) and len(obj) > _LOG_MAX_STR:
        return obj[:_LOG_MAX_STR] + f"...<+{len(obj) - _LOG_MAX_STR} chars>"
    return obj


def _log_path() -> Path | None:
    project_id = os.environ.get("SPARK_VIDEO_PROJECT")
    if not project_id:
        return None
    episode_id = os.environ.get("SPARK_VIDEO_EPISODE")
    base = Path(os.environ.get("VIDEOGEN_PROJECTS_DIR", "./projects")).resolve() / project_id
    if episode_id:
        ep = episode_id if episode_id.startswith("episode-") else f"episode-{episode_id}"
        base = base / ep
    return base / "logs" / "model_calls.jsonl"


def _log_call(
    *,
    kind: str,
    model: str | None,
    endpoint: str,
    request: Any = None,
    response: Any = None,
    task_id: str | None = None,
    duration_ms: float | None = None,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    try:
        path = _log_path()
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "kind": kind,
            "project_id": os.environ.get("SPARK_VIDEO_PROJECT"),
            "episode_id": os.environ.get("SPARK_VIDEO_EPISODE"),
            "shot_id": os.environ.get("SPARK_VIDEO_SHOT"),
            "version": int(os.environ["SPARK_VIDEO_ATTEMPT"])
            if os.environ.get("SPARK_VIDEO_ATTEMPT")
            else None,
            "provider": "seedance2",
            "model": model,
            "endpoint": endpoint,
            "task_id": task_id,
            "duration_ms": round(duration_ms, 2) if duration_ms is not None else None,
            "request": _truncate_for_log(request) if request is not None else None,
            "response": _truncate_for_log(response) if response is not None else None,
            "error": error,
            "extra": _truncate_for_log(extra) if extra else None,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        return


def _json_or_text(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {"text": resp.text[:4000]}


def _request_json(
    method: str,
    endpoint: str,
    *,
    model: str,
    body: dict[str, Any] | None = None,
    task_id: str | None = None,
    kind: str,
) -> dict[str, Any]:
    started = time.time()
    try:
        resp = requests.request(
            method,
            endpoint,
            headers=_headers(),
            json=body,
            timeout=60,
        )
        elapsed_ms = (time.time() - started) * 1000
        data = _json_or_text(resp)
        if not resp.ok:
            error = (
                f"HTTP {resp.status_code}: "
                f"{json.dumps(data, ensure_ascii=False)[:1200]}"
            )
            _log_call(
                kind=kind,
                model=model,
                endpoint=endpoint,
                request=body,
                response=data,
                task_id=task_id,
                duration_ms=elapsed_ms,
                error=error,
            )
            raise RuntimeError(error)
        if not isinstance(data, dict):
            raise RuntimeError(f"Ark returned non-object JSON: {data!r}")
        _log_call(
            kind=kind,
            model=model,
            endpoint=endpoint,
            request=body,
            response=data,
            task_id=task_id or _extract_task_id(data),
            duration_ms=elapsed_ms,
        )
        return data
    except Exception as e:
        if not isinstance(e, RuntimeError):
            _log_call(
                kind=kind,
                model=model,
                endpoint=endpoint,
                request=body,
                task_id=task_id,
                duration_ms=(time.time() - started) * 1000,
                error=str(e),
            )
        raise


def _extract_task_id(data: dict[str, Any]) -> str | None:
    for key in ("id", "task_id"):
        value = data.get(key)
        if value:
            return str(value)
    for key in ("output", "data"):
        nested = data.get(key)
        if isinstance(nested, dict):
            value = nested.get("task_id") or nested.get("id")
            if value:
                return str(value)
    return None


def _status(data: dict[str, Any]) -> str:
    value = data.get("status")
    if not value and isinstance(data.get("output"), dict):
        value = data["output"].get("task_status")
    return str(value or "").strip().lower()


def _content_dicts(data: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for container in (data, data.get("data"), data.get("output")):
        if not isinstance(container, dict):
            continue
        content = container.get("content")
        if isinstance(content, dict):
            out.append(content)
        elif isinstance(content, list):
            out.extend(x for x in content if isinstance(x, dict))
    return out


def _extract_video_url(data: dict[str, Any]) -> str | None:
    for obj in _content_dicts(data):
        if obj.get("video_url"):
            value = obj["video_url"]
            if isinstance(value, dict):
                return value.get("url")
            return str(value)
        if obj.get("url") and obj.get("type") in (None, "video_url", "video"):
            return str(obj["url"])
    for container in (data, data.get("data"), data.get("output")):
        if isinstance(container, dict) and container.get("video_url"):
            return str(container["video_url"])
    return None


def _extract_last_frame_url(data: dict[str, Any]) -> str | None:
    for obj in _content_dicts(data):
        value = obj.get("last_frame_url")
        if value:
            return str(value)
    return None


def _submit(model: str, body: dict[str, Any]) -> str:
    endpoint = f"{ARK_BASE}/contents/generations/tasks"
    data = _request_json(
        "POST",
        endpoint,
        model=model,
        body=body,
        kind="video_submit",
    )
    task_id = _extract_task_id(data)
    if not task_id:
        raise RuntimeError(f"submit returned no task id: {data}")
    return task_id


def _wait(task_id: str, model: str, timeout_s: int) -> dict[str, Any]:
    endpoint = f"{ARK_BASE}/contents/generations/tasks/{task_id}"
    deadline = time.time() + timeout_s
    poll = int(
        os.environ.get(
            "SEEDANCE2_POLL_INTERVAL",
            os.environ.get("VIDEOGEN_POLL_INTERVAL", "10"),
        )
    )
    poll = max(2, poll)

    while time.time() < deadline:
        data = _request_json(
            "GET",
            endpoint,
            model=model,
            task_id=task_id,
            kind="video_wait",
        )
        status = _status(data)
        if status in _SUCCESS_STATUSES:
            if not _extract_video_url(data):
                raise RuntimeError(
                    f"task {task_id} succeeded but returned no video_url: {data}"
                )
            return data
        if status in _FAILED_STATUSES:
            raise RuntimeError(f"task {task_id} {status}: {data}")
        time.sleep(poll)
        poll = min(poll + 2, 15)

    raise TimeoutError(f"task {task_id} timed out after {timeout_s}s")


def _download(url: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        with out_path.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)


def render(
    *,
    kind: Literal["t2v", "i2v", "r2v"],
    prompt: str,
    media: list[str | Path] | None = None,
    voice: str | Path | None = None,
    duration: int,
    out_path: Path,
    extra: dict | None = None,
) -> dict:
    media = media or []
    extra = extra or {}
    out_path = Path(out_path)

    model = str(extra.get("model") or DEFAULT_MODEL)
    duration = max(2, min(15, int(duration)))
    content = _build_content(
        kind=kind,
        prompt=prompt,
        media=media,
        voice=voice,
        extra=extra,
    )

    body: dict[str, Any] = {
        "model": model,
        "content": content,
        "generate_audio": bool(
            extra.get("generate_audio", _bool_env("SEEDANCE2_GENERATE_AUDIO", True))
        ),
        "duration": duration,
        "watermark": bool(
            extra.get("watermark", _bool_env("SEEDANCE2_WATERMARK", False))
        ),
    }

    ratio = extra.get("ratio") or os.environ.get("SEEDANCE2_RATIO")
    if ratio:
        body["ratio"] = str(ratio)
    resolution = _normalise_resolution(
        extra.get("resolution") or os.environ.get("SEEDANCE2_RESOLUTION")
    )
    if resolution:
        body["resolution"] = resolution
    if extra.get("seed") is not None:
        body["seed"] = int(extra["seed"])
    if extra.get("return_last_frame") is not None:
        body["return_last_frame"] = bool(extra["return_last_frame"])
    elif _bool_env("SEEDANCE2_RETURN_LAST_FRAME", False):
        body["return_last_frame"] = True

    started = time.time()
    task_id = _submit(model, body)
    timeout_s = int(os.environ.get("SPARK_VIDEO_RENDER_TIMEOUT_S", "900"))
    final = _wait(task_id, model, timeout_s=timeout_s)
    video_url = _extract_video_url(final)
    if not video_url:
        raise RuntimeError(f"task {task_id} returned no video_url: {final}")
    _download(video_url, out_path)
    elapsed = time.time() - started

    return {
        "video_path": str(out_path),
        "model": model,
        "elapsed_s": round(elapsed, 2),
        "task_id": task_id,
        "last_frame_url": _extract_last_frame_url(final),
    }
