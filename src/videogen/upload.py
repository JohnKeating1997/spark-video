"""Upload local files to DashScope's instant OSS bucket and get an oss:// URL.

DashScope video APIs (Wan 2.7 / HappyHorse 1.0) accept either
``oss://dashscope-instant/...`` or public HTTPS URLs in ``media[].url``.
For local cast assets we use this path so users don't need their own OSS.

Refs: https://help.aliyun.com/zh/model-studio/get-temporary-file-url
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import dashscope

from .config import SETTINGS

Purpose = Literal["video-generation"]

# DashScope's "getPolicy" requires a model name to scope the upload certificate.
# Any video-generation model works; the resulting oss://dashscope-instant
# URL is reusable across all video model families. We default to wan2.7-r2v
# because the upload helper has been validated against it; HappyHorse-uploaded
# OSS URLs are interchangeable.
_DEFAULT_MODEL = "wan2.7-r2v"


def upload(
    local_path: str | Path,
    *,
    purpose: Purpose = "video-generation",  # noqa: ARG001 — kept for API compat
    model: str = _DEFAULT_MODEL,
) -> str:
    """Returns an oss:// URL usable as ``media[].url`` in any video-generation request."""
    p = Path(local_path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(p)

    api_key = SETTINGS.require_api_key()
    dashscope.api_key = api_key
    dashscope.base_http_api_url = SETTINGS.base_url

    try:
        from dashscope.utils.oss_utils import OssUtils
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Could not locate dashscope OSS upload helper. "
            "Upgrade dashscope (`pip install -U dashscope`) or upload the file "
            "to your own public URL."
        ) from e

    result = OssUtils.upload(model=model, file_path=str(p), api_key=api_key)

    # Different dashscope versions return either a bare oss:// URL string or a
    # (url, policy_dict) tuple. Normalise to the URL.
    if isinstance(result, tuple) and result:
        oss_url = result[0]
    else:
        oss_url = result

    if not isinstance(oss_url, str) or not oss_url.startswith("oss://"):
        raise RuntimeError(f"Unexpected upload result: {result!r}")
    return oss_url
