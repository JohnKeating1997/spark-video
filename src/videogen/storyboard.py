"""Storyboard schema. The LLM (导演 Skill) emits storyboard.json conforming to this.

Each shot will be turned into one Wan request by `videogen render`.

Per-model duration ceilings (from api-references/wan/*.md):
    wan2.7-t2v-2026-04-25  → 2..15s
    wan2.7-i2v-2026-04-25  → 2..15s
    wan2.7-r2v             → 2..15s (2..10s when reference_video is used; we do not use it)
    wan2.7-videoedit       → 2..10s

We default each shot to 15s — the max for our active models — to minimize
cuts and maximize cross-shot continuity. Override per shot if you genuinely
need a quick beat.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Single source of truth for per-model duration limits.
MODEL_MAX_DURATION: dict[str, int] = {
    "wan2.7-r2v": 15,
    "wan2.7-i2v-2026-04-25": 15,
    "wan2.7-t2v-2026-04-25": 15,
    "wan2.7-videoedit": 10,
}
DEFAULT_DURATION = 15
DURATION_FLOOR = 2


class Shot(BaseModel):
    id: str = Field(description="shot id, e.g. 'S01-001' (scene-shot)")
    scene: str = Field(description="logical scene id, e.g. 'S01'")
    duration: int = Field(
        default=DEFAULT_DURATION,
        ge=DURATION_FLOOR,
        le=15,
        description="seconds. Default = 15 (max). Auto-clamped to model ceiling at validation.",
    )
    prompt: str = Field(description="Wan prompt — describe action, camera, mood")
    negative_prompt: str | None = None

    # Character references — names must match cast.json
    characters: list[str] = Field(default_factory=list, description="cast names featured")

    # Continuity
    use_prev_last_frame_as_first: bool = Field(
        default=True,
        description="If true, ffmpeg extracts last frame of previous successful shot and feeds as first_frame.",
    )

    model: Literal[
        "wan2.7-r2v",
        "wan2.7-i2v-2026-04-25",
        "wan2.7-t2v-2026-04-25",
    ] = "wan2.7-r2v"

    seed: int | None = None
    candidates: int = Field(default=1, ge=1, le=4, description="N抽卡候选")

    @field_validator("prompt")
    @classmethod
    def _no_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("prompt is empty")
        return v

    @model_validator(mode="after")
    def _clamp_duration_to_model(self) -> "Shot":
        ceiling = MODEL_MAX_DURATION.get(self.model, 15)
        if self.duration > ceiling:
            object.__setattr__(self, "duration", ceiling)
        return self


class Scene(BaseModel):
    """A logical scene — one location + time + situation.

    The director defines all scenes BEFORE writing individual shots.
    Every shot in a scene inherits its environment description, ensuring
    visual consistency even though the video model has no memory.
    """
    id: str = Field(description="scene id, e.g. 'S01'. Must match shot.scene references.")
    name: str = Field(description="short human label, e.g. '七侠镇戏台子·白天'")
    description: str = Field(
        description=(
            "Detailed environment description (50-150 chars). Includes: "
            "location, time of day, lighting, props, atmosphere. "
            "This is prepended/woven into EVERY shot prompt in this scene."
        )
    )
    characters_present: list[str] = Field(
        default_factory=list,
        description="All characters who appear at some point in this scene (for recall).",
    )
    seed: int | None = Field(
        default=None,
        description="Shared seed for all shots in this scene (Rule 4 of continuity).",
    )

    @field_validator("description")
    @classmethod
    def _desc_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("scene description is empty")
        return v


class Storyboard(BaseModel):
    project_id: str
    title: str
    synopsis: str
    target_duration_s: int = Field(default=180, ge=2, description="user's intended target; informational only")
    resolution: str = "720P"
    ratio: str = "16:9"
    scenes: list[Scene] = Field(
        default_factory=list,
        description=(
            "Explicit scene definitions. Each scene carries a detailed environment "
            "description that MUST be woven into every shot in that scene. "
            "If empty (legacy), shots still work but lose scene-level consistency."
        ),
    )
    shots: list[Shot]

    def total_duration(self) -> int:
        return sum(s.duration for s in self.shots)

    def estimated_wall_clock_min(self, *, avg_per_shot_s: int = 180) -> float:
        """Sequential render assumption — each shot waits 1–5 min for Wan."""
        return (len(self.shots) * avg_per_shot_s) / 60.0

    def scene_map(self) -> dict[str, Scene]:
        """Return {scene.id: Scene} for quick lookup."""
        return {s.id: s for s in self.scenes}

    def lint(self) -> list[str]:
        """Soft continuity / pacing checks. Never blocks render."""
        warnings: list[str] = []
        # First shot cannot chain.
        if self.shots and self.shots[0].use_prev_last_frame_as_first:
            warnings.append(
                f"first shot {self.shots[0].id}: use_prev_last_frame_as_first=true "
                f"but no previous shot exists — set it to false."
            )
        # i2v shots that need a previous frame but the previous shot doesn't chain.
        for i, s in enumerate(self.shots):
            if s.model == "wan2.7-i2v-2026-04-25" and not s.use_prev_last_frame_as_first:
                warnings.append(
                    f"{s.id}: i2v with use_prev_last_frame_as_first=false will fail "
                    f"unless you supply media manually (not currently supported)."
                )
        # Duplicate shot ids.
        ids: dict[str, int] = {}
        for s in self.shots:
            ids[s.id] = ids.get(s.id, 0) + 1
        for sid, n in ids.items():
            if n > 1:
                warnings.append(f"duplicate shot id {sid!r} appears {n} times")

        # Orphaned action chains: 3+ consecutive shots with no characters
        # in the same scene usually means the protagonist dropped out.
        run_start = -1
        for i, s in enumerate(self.shots):
            if not s.characters and s.model != "wan2.7-t2v-2026-04-25":
                if run_start < 0:
                    run_start = i
            else:
                if run_start >= 0 and (i - run_start) >= 3:
                    ids_str = ", ".join(self.shots[j].id for j in range(run_start, i))
                    warnings.append(
                        f"protagonist dropout: {i - run_start} consecutive shots "
                        f"({ids_str}) have no characters — if this is an action "
                        f"sequence, the subject (e.g. the person being attacked) "
                        f"must stay in frame. Add them to characters[] and use r2v."
                    )
                run_start = -1
        # Check tail
        if run_start >= 0 and (len(self.shots) - run_start) >= 3:
            ids_str = ", ".join(self.shots[j].id for j in range(run_start, len(self.shots)))
            warnings.append(
                f"protagonist dropout: {len(self.shots) - run_start} consecutive shots "
                f"({ids_str}) have no characters at the end of the storyboard."
            )

        # Scene definition checks
        scene_map = self.scene_map()
        if self.scenes:
            shot_scene_ids = {s.scene for s in self.shots}
            defined_ids = {s.id for s in self.scenes}
            # Shots referencing undefined scenes
            undefined = shot_scene_ids - defined_ids
            if undefined:
                warnings.append(
                    f"shots reference undefined scenes: {', '.join(sorted(undefined))}. "
                    f"Add them to the 'scenes' array."
                )
            # Defined scenes with no shots
            unused = defined_ids - shot_scene_ids
            if unused:
                warnings.append(
                    f"scenes defined but never used by any shot: {', '.join(sorted(unused))}"
                )
            # Characters in shots but not in scene.characters_present
            for s in self.shots:
                sc = scene_map.get(s.scene)
                if sc and s.characters:
                    missing = set(s.characters) - set(sc.characters_present)
                    if missing:
                        warnings.append(
                            f"{s.id}: characters {missing} appear in shot but not in "
                            f"scene {sc.id}.characters_present — add them for recall."
                        )

        return warnings
