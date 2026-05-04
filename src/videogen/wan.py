"""Thin Wan API client — submit + poll for t2v / i2v / r2v / videoedit.

We use plain httpx instead of dashscope SDK so failures are transparent and
results are easy to log/replay. Async tasks always go through the
'X-DashScope-Async: enable' channel.
"""
from __future__ import annotations

import time
from typing import Any, Literal

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import SETTINGS

ModelKind = Literal[
    "wan2.7-t2v-2026-04-25",
    "wan2.7-i2v-2026-04-25",
    "wan2.7-r2v",
    "wan2.7-videoedit",
]

SUBMIT_PATH = "/services/aigc/video-generation/video-synthesis"


def _headers(extra: dict | None = None) -> dict:
    h = {
        "Authorization": f"Bearer {SETTINGS.require_api_key()}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    if extra:
        h.update(extra)
    return h


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
def submit(
    model: ModelKind,
    *,
    input: dict,
    parameters: dict | None = None,
) -> dict:
    """Create an async task. Returns full response (incl. task_id)."""
    body: dict[str, Any] = {"model": model, "input": input}
    if parameters:
        body["parameters"] = parameters

    url = SETTINGS.base_url + SUBMIT_PATH
    with httpx.Client(timeout=60.0) as c:
        r = c.post(url, json=body, headers=_headers())
        r.raise_for_status()
        data = r.json()
    if data.get("code"):
        raise RuntimeError(f"Wan submit failed: {data}")
    return data


@retry(stop=stop_after_attempt(5), wait=wait_exponential(min=2, max=20))
def query(task_id: str) -> dict:
    url = f"{SETTINGS.base_url}/tasks/{task_id}"
    with httpx.Client(timeout=30.0) as c:
        r = c.get(url, headers={"Authorization": f"Bearer {SETTINGS.require_api_key()}"})
        r.raise_for_status()
        return r.json()


TERMINAL = {"SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"}


def wait(task_id: str, *, interval: int | None = None, timeout_s: int = 1800) -> dict:
    """Poll until task reaches a terminal state. Default timeout 30 min."""
    interval = interval or SETTINGS.poll_interval
    start = time.time()
    while True:
        data = query(task_id)
        status = data.get("output", {}).get("task_status")
        if status in TERMINAL:
            return data
        if time.time() - start > timeout_s:
            raise TimeoutError(f"task {task_id} stuck in {status} for {timeout_s}s")
        time.sleep(interval)
