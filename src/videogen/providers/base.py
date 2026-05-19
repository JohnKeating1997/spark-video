"""Abstract base for video model providers.

A provider knows three things:

1. **Model naming** — generic ``ShotKind`` → concrete model name string.
2. **Request shape** — how to build ``input`` and ``parameters`` for the
   DashScope video-synthesis endpoint (per-vendor quirks).
3. **Capabilities** — which optional features the vendor supports, so the
   render driver can degrade gracefully (e.g. drop ``reference_voice`` when
   HappyHorse is active).

The DashScope async lifecycle (submit → poll → terminal) is shared
infrastructure and lives here too. Per-vendor providers only override the
parts that genuinely differ.
"""
from __future__ import annotations

import time
from typing import Any, Literal

import httpx
from rich.console import Console
from tenacity import retry, stop_after_attempt, wait_exponential

from .. import model_log
from ..config import SETTINGS

console = Console()

ShotKind = Literal["t2v", "i2v", "r2v"]
ProviderName = Literal["wan", "happyhorse"]
Feature = Literal[
    "reference_voice",       # r2v media[].reference_voice (Wan only)
    "first_frame_in_r2v",    # r2v media[type=first_frame] for chain bridging
    "prompt_extend",         # parameters.prompt_extend
    "negative_prompt",       # input.negative_prompt
    "i2v_ratio",             # i2v parameters.ratio (HappyHorse i2v ignores it)
]

SUBMIT_PATH = "/services/aigc/video-generation/video-synthesis"
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"}


class BuildResult(dict):
    """Lightweight typed dict for ``provider.build_request`` output.

    Keys:
      * ``model``            — concrete model name to submit
      * ``input``            — request body's ``input`` object
      * ``parameters``       — request body's ``parameters`` object
      * ``effective_kind``   — kind actually rendered (after auto-demote)
      * ``warnings``         — non-fatal messages to surface to the user
    """


class VideoProvider:
    """Abstract base. Subclasses set ``name`` + the four ``_*`` helpers."""

    name: ProviderName

    # Per-kind default model name. Subclasses override.
    models: dict[ShotKind, str]

    # Per-kind duration limits. Subclasses override.
    duration_min: dict[ShotKind, int]
    duration_max: dict[ShotKind, int]

    # Feature support set. Subclasses override.
    features: frozenset[Feature]

    # ── public API ────────────────────────────────────────────────────────

    def model_for(self, kind: ShotKind) -> str:
        try:
            return self.models[kind]
        except KeyError as e:
            raise ValueError(
                f"provider {self.name!r} does not support kind {kind!r}; "
                f"valid kinds: {sorted(self.models)}"
            ) from e

    def max_duration(self, kind: ShotKind) -> int:
        return self.duration_max.get(kind, 15)

    def min_duration(self, kind: ShotKind) -> int:
        return self.duration_min.get(kind, 2)

    def supports(self, feature: Feature) -> bool:
        return feature in self.features

    # ── request building ──────────────────────────────────────────────────

    def build_request(
        self,
        shot,                                  # videogen.storyboard.Shot
        *,
        storyboard,                            # videogen.storyboard.Storyboard
        prompt: str,
        cast_data: dict,
        prev_last_frame_url: str | None,
        scene=None,                            # videogen.storyboard.Scene | None
        movie_set_data: dict | None = None,    # videogen.movie_set.load() shape
        prop_data: dict | None = None,         # videogen.prop.load() shape
    ) -> BuildResult:
        """Subclasses implement. Returns BuildResult dict.

        ``scene`` + ``movie_set_data`` let providers append the scene's
        set reference image to r2v shots; ``prop_data`` does the same
        for each name in ``shot.props``. All three are optional —
        t2v / i2v shots and shots without props/set_id ignore them.

        Reference-image priority order in r2v media[]:
          1. cast portraits (one per shot.characters)
          2. scene/shot effective set image (one)
          3. shot.props reference images (one per prop)
          4. (Wan only) chained first_frame for use_prev_last_frame_as_first
        Providers with a media-slot cap drop later items first.
        """
        raise NotImplementedError

    # ── async lifecycle (shared) ──────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {SETTINGS.require_api_key()}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
            "X-DashScope-OssResourceResolve": "enable",
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
    def submit(
        self,
        model: str,
        *,
        input: dict,
        parameters: dict | None = None,
    ) -> dict:
        body: dict[str, Any] = {"model": model, "input": input}
        if parameters:
            body["parameters"] = parameters
        url = SETTINGS.base_url + SUBMIT_PATH
        t0 = time.time()
        data: dict | None = None
        err: str | None = None
        try:
            with httpx.Client(timeout=60.0) as c:
                r = c.post(url, json=body, headers=self._headers())
                r.raise_for_status()
                data = r.json()
            if data.get("code"):
                raise RuntimeError(f"{self.name} submit failed: {data}")
            return data
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            raise
        finally:
            model_log.log_call(
                kind="video_submit",
                provider=self.name,
                model=model,
                endpoint=url,
                request=body,
                response=data,
                task_id=(data or {}).get("output", {}).get("task_id"),
                duration_ms=(time.time() - t0) * 1000,
                error=err,
            )

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(min=2, max=20))
    def query(self, task_id: str) -> dict:
        url = f"{SETTINGS.base_url}/tasks/{task_id}"
        with httpx.Client(timeout=30.0) as c:
            r = c.get(
                url,
                headers={"Authorization": f"Bearer {SETTINGS.require_api_key()}"},
            )
            r.raise_for_status()
            return r.json()

    def wait(
        self,
        task_id: str,
        *,
        interval: int | None = None,
        timeout_s: int = 1800,
    ) -> dict:
        interval = interval or SETTINGS.poll_interval
        start = time.time()
        # We deliberately do NOT log every poll (would balloon the JSONL).
        # Only the terminal result is logged below — task_id ties it back
        # to the submit record.
        while True:
            data = self.query(task_id)
            status = data.get("output", {}).get("task_status")
            if status in TERMINAL:
                model_log.log_call(
                    kind="video_wait",
                    provider=self.name,
                    endpoint=f"{SETTINGS.base_url}/tasks/{task_id}",
                    task_id=task_id,
                    response=data,
                    duration_ms=(time.time() - start) * 1000,
                    extra={"terminal_status": status, "poll_interval_s": interval},
                )
                return data
            if time.time() - start > timeout_s:
                model_log.log_call(
                    kind="video_wait",
                    provider=self.name,
                    endpoint=f"{SETTINGS.base_url}/tasks/{task_id}",
                    task_id=task_id,
                    response=data,
                    duration_ms=(time.time() - start) * 1000,
                    error=f"timeout after {timeout_s}s in status {status}",
                    extra={"terminal_status": status, "poll_interval_s": interval},
                )
                raise TimeoutError(f"task {task_id} stuck in {status} for {timeout_s}s")
            time.sleep(interval)
