"""Upload local files to DashScope's instant OSS bucket and get an oss:// URL.

Wan API accepts oss://dashscope-instant/... or public HTTPS URLs.
For local cast assets we use this path so users don't need their own OSS.

Refs: https://help.aliyun.com/zh/model-studio/get-temporary-file-url
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import dashscope

from .config import SETTINGS

Purpose = Literal["video-generation"]


def upload(local_path: str | Path, *, purpose: Purpose = "video-generation") -> str:
    """Returns an oss:// URL usable as media `url` in Wan requests."""
    p = Path(local_path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(p)

    dashscope.api_key = SETTINGS.require_api_key()
    dashscope.base_http_api_url = SETTINGS.base_url

    # The DashScope SDK exposes a file-upload helper used internally for
    # async media inputs. Using the underlying session keeps it minimal.
    from dashscope.common.api_key import get_default_api_key  # noqa: F401  (ensures init)
    from dashscope.api_entities.dashscope_response import DashScopeAPIResponse  # noqa: F401

    # NOTE: The exact upload helper may differ by SDK minor version. Adjust here
    # if dashscope changes its API. See
    # https://help.aliyun.com/zh/model-studio/get-temporary-file-url for canonical flow.
    try:
        from dashscope.utils.oss_utils import _upload_to_oss  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Could not locate dashscope OSS upload helper. "
            "Upgrade dashscope (>=1.25.16) or upload the file to your own public URL."
        ) from e

    oss_url = _upload_to_oss(str(p), SETTINGS.require_api_key())
    if not oss_url or not oss_url.startswith("oss://"):
        raise RuntimeError(f"Unexpected upload result: {oss_url!r}")
    return oss_url
