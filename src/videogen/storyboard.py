"""Storyboard schema. The LLM (导演 Skill) emits storyboard.json conforming to this.

Each shot will be turned into one Wan request by `videogen render`.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Shot(BaseModel):
    id: str = Field(description="shot id, e.g. 'S01-001' (scene-shot)")
    scene: str = Field(description="logical scene id, e.g. 'S01'")
    duration: int = Field(default=8, ge=2, le=15)
    prompt: str = Field(description="Wan prompt — describe action, camera, mood")
    negative_prompt: str | None = None

    # Character references — names must match cast.json
    characters: list[str] = Field(default_factory=list, description="cast names featured")

    # Continuity
    use_prev_last_frame_as_first: bool = Field(
        default=True,
        description="If true, ffmpeg extracts last frame of previous successful shot and feeds as first_frame.",
    )

    # Model selection — Skill picks one based on shot needs.
    model: Literal[
        "wan2.7-r2v",  # default for character/dialog shots
        "wan2.7-i2v-2026-04-25",  # pure visual transitions
        "wan2.7-t2v-2026-04-25",  # establishing/wide w/o specific cast
    ] = "wan2.7-r2v"

    seed: int | None = None
    candidates: int = Field(default=1, ge=1, le=4, description="N抽卡候选")

    @field_validator("prompt")
    @classmethod
    def _no_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("prompt is empty")
        return v


class Storyboard(BaseModel):
    project_id: str
    title: str
    synopsis: str
    target_duration_s: int = Field(default=180, ge=30)
    resolution: str = "720P"
    ratio: str = "16:9"
    shots: list[Shot]

    def total_duration(self) -> int:
        return sum(s.duration for s in self.shots)
