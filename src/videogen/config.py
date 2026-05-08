from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    api_key: str
    region: str
    base_url: str
    resolution: str
    ratio: str
    clip_duration: int
    long_confirm_s: int
    max_concurrency: int
    poll_interval: int
    projects_dir: Path
    # Per-clip review + auto-rewrite (Zone 3 of the multi-agent pipeline).
    review_threshold: float
    review_model: str
    rewrite_model: str
    max_retry: int

    @classmethod
    def load(cls) -> "Settings":
        region = os.getenv("VIDEOGEN_REGION", "beijing").lower()
        if region == "singapore":
            base = "https://dashscope-intl.aliyuncs.com/api/v1"
        else:
            base = "https://dashscope.aliyuncs.com/api/v1"

        api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        return cls(
            api_key=api_key,
            region=region,
            base_url=base,
            resolution=os.getenv("VIDEOGEN_DEFAULT_RESOLUTION", "720P"),
            ratio=os.getenv("VIDEOGEN_DEFAULT_RATIO", "16:9"),
            clip_duration=int(os.getenv("VIDEOGEN_DEFAULT_CLIP_DURATION", "15")),
            long_confirm_s=int(os.getenv("VIDEOGEN_LONG_CONFIRM_S", "180")),
            max_concurrency=int(os.getenv("VIDEOGEN_MAX_CONCURRENCY", "4")),
            poll_interval=int(os.getenv("VIDEOGEN_POLL_INTERVAL", "15")),
            projects_dir=Path(os.getenv("VIDEOGEN_PROJECTS_DIR", "./projects")).resolve(),
            review_threshold=float(os.getenv("VIDEOGEN_REVIEW_THRESHOLD", "7.0")),
            review_model=os.getenv("VIDEOGEN_REVIEW_MODEL", "qwen3-vl-plus").strip(),
            rewrite_model=os.getenv("VIDEOGEN_REWRITE_MODEL", "qwen-plus").strip(),
            max_retry=int(os.getenv("VIDEOGEN_MAX_RETRY", "3")),
        )

    def require_api_key(self) -> str:
        if not self.api_key:
            raise RuntimeError(
                "DASHSCOPE_API_KEY is missing. Copy .env.example to .env and fill it in."
            )
        return self.api_key


SETTINGS = Settings.load()
