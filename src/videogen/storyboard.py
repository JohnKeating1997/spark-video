"""Storyboard schema — provider-agnostic.

Each shot will be turned into one DashScope video-synthesis request by
``videogen render``. The shot itself only declares a generic *kind*
(``t2v`` | ``i2v`` | ``r2v``). Mapping to a concrete model name is the
provider's job — see ``src/videogen/providers/``.

Per-kind duration ceilings (worst case across providers; the active
provider may impose a tighter cap of its own):

    t2v  → 2..15s
    i2v  → 2..15s
    r2v  → 2..15s

We default each shot to 15s — the max for our active models — to minimize
cuts and maximize cross-shot continuity. Override per shot if you genuinely
need a quick beat. Each provider also enforces its own duration *floor*
(Wan: 2s, HappyHorse: 3s).

Backward-compat: if ``Shot`` JSON still carries the old ``model`` field
with a ``wan2.7-*`` or ``happyhorse-1.0-*`` literal, we transparently
translate it to the new ``kind`` field on validate.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ShotKind = Literal["t2v", "i2v", "r2v"]
ProviderName = Literal["wan", "happyhorse"]

# Per-kind worst-case duration ceiling. Provider-specific ceilings live on
# the provider class itself; this is the schema-level fallback.
KIND_MAX_DURATION: dict[str, int] = {"t2v": 15, "i2v": 15, "r2v": 15}
DEFAULT_DURATION = 15
DURATION_FLOOR = 2

# Legacy provider-specific model strings that may still appear in old
# ``storyboard.json`` files. Mapped to (kind, provider) on read so the
# whole pipeline keeps working without manual migration.
LEGACY_MODEL_TO_KIND: dict[str, tuple[ShotKind, ProviderName]] = {
    "wan2.7-r2v":              ("r2v", "wan"),
    "wan2.7-i2v-2026-04-25":   ("i2v", "wan"),
    "wan2.7-t2v-2026-04-25":   ("t2v", "wan"),
    "happyhorse-1.0-r2v":      ("r2v", "happyhorse"),
    "happyhorse-1.0-i2v":      ("i2v", "happyhorse"),
    "happyhorse-1.0-t2v":      ("t2v", "happyhorse"),
}


class Shot(BaseModel):
    id: str = Field(description="shot id, e.g. 'S01-001' (scene-shot)")
    scene: str = Field(description="logical scene id, e.g. 'S01'")
    duration: int = Field(
        default=DEFAULT_DURATION,
        ge=DURATION_FLOOR,
        le=15,
        description="seconds. Default = 15. Auto-clamped to provider ceiling/floor at render time.",
    )
    prompt: str = Field(description="video prompt — describe action, camera, mood")
    negative_prompt: str | None = Field(
        default=None,
        description=(
            "Optional negative prompt. Honored by Wan only — HappyHorse "
            "ignores it (the render driver logs a warning)."
        ),
    )

    # ── 山音融合 ──────────────────────────────────────────
    # Why this shot exists in the story. Specific to visual means
    # (e.g. "用低角度仰拍 + 缓慢推近放大钱夫人的优越感"), not vague labels
    # (e.g. "展现冲突"). The CLI doesn't render this — it's metadata for
    # the director's own discipline + VFX reviewer's quality gate.
    narrative_purpose: str | None = Field(
        default=None,
        description=(
            "山音融合：每个 shot 必填。具体到视听手段, 不写'展现冲突'等空话。"
        ),
    )
    # Optional shot-group affiliation (山音"镜头组"概念)。同组镜头共同
    # 完成一个叙事单元 (蒙太奇组 / 递进组 / 因果组 / 对比组)。
    shot_group_id: str | None = Field(default=None, description="e.g. 'G01'")
    shot_group_role: Literal[
        "建立", "递进", "反应", "对比", "收尾"
    ] | None = None
    # ──────────────────────────────────────────────────────

    # Character references — names must match cast.json
    characters: list[str] = Field(default_factory=list, description="cast names featured")

    # Continuity
    use_prev_last_frame_as_first: bool = Field(
        default=True,
        description="If true, ffmpeg extracts last frame of previous successful shot and feeds as first_frame.",
    )

    kind: ShotKind = Field(
        default="r2v",
        description=(
            "Generic shot kind. The active provider (wan / happyhorse) maps "
            "this to a concrete model name at render time. Choose r2v for "
            "character-driven shots with cast references, t2v for "
            "establishing shots with no cast lock, i2v for first-frame "
            "continuation within a chain group."
        ),
    )

    seed: int | None = None
    candidates: int = Field(default=1, ge=1, le=4, description="N抽卡候选")

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_model(cls, data: Any) -> Any:
        """Translate legacy ``model: "wan2.7-*" | "happyhorse-1.0-*"`` to ``kind``.

        Old storyboards predate the provider abstraction — they wrote out
        the concrete model name directly. We accept those silently so users
        don't have to hand-edit storyboard.json.
        """
        if not isinstance(data, dict):
            return data
        if "kind" in data and data["kind"]:
            # Already in new format. Drop a stale ``model`` key if present.
            data.pop("model", None)
            return data
        legacy = data.pop("model", None)
        if legacy is None:
            return data
        mapping = LEGACY_MODEL_TO_KIND.get(str(legacy))
        if mapping is None:
            raise ValueError(
                f"unknown legacy model {legacy!r}. Valid legacy values: "
                f"{sorted(LEGACY_MODEL_TO_KIND)}. Migrate this shot to use "
                f"the new ``kind`` field (t2v|i2v|r2v)."
            )
        kind, _provider = mapping
        data["kind"] = kind
        return data

    @field_validator("prompt")
    @classmethod
    def _no_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("prompt is empty")
        return v

    @model_validator(mode="after")
    def _clamp_duration_to_kind(self) -> "Shot":
        ceiling = KIND_MAX_DURATION.get(self.kind, 15)
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
    provider: ProviderName | None = Field(
        default=None,
        description=(
            "Video model family for this episode (wan | happyhorse). When "
            "absent, the renderer falls back to the VIDEOGEN_VIDEO_PROVIDER "
            "env var, then the built-in default (happyhorse)."
        ),
    )
    scenes: list[Scene] = Field(
        default_factory=list,
        description=(
            "Explicit scene definitions. Each scene carries a detailed environment "
            "description that MUST be woven into every shot in that scene. "
            "If empty (legacy), shots still work but lose scene-level consistency."
        ),
    )
    shots: list[Shot]

    @model_validator(mode="before")
    @classmethod
    def _infer_legacy_provider(cls, data: Any) -> Any:
        """If the storyboard predates the provider field, infer it from the
        first shot's legacy ``model`` so re-rendering an old episode
        deterministically picks the original family."""
        if not isinstance(data, dict):
            return data
        if data.get("provider"):
            return data
        for shot in data.get("shots") or []:
            if isinstance(shot, dict) and shot.get("model"):
                mapping = LEGACY_MODEL_TO_KIND.get(str(shot["model"]))
                if mapping:
                    data["provider"] = mapping[1]
                    break
        return data

    def total_duration(self) -> int:
        return sum(s.duration for s in self.shots)

    def estimated_wall_clock_min(self, *, avg_per_shot_s: int = 180) -> float:
        """Sequential render assumption — each shot waits 1–5 min upstream."""
        return (len(self.shots) * avg_per_shot_s) / 60.0

    def scene_map(self) -> dict[str, Scene]:
        """Return {scene.id: Scene} for quick lookup."""
        return {s.id: s for s in self.scenes}

    def lint(self) -> list[str]:
        """Soft continuity / pacing checks. Never blocks render."""
        warnings: list[str] = []

        # 山音融合: every shot should have a non-trivial narrative_purpose.
        # Soft warning only — never blocks render. VFX reviewer enforces.
        _vague = {
            "", "展现冲突", "推进剧情", "推进故事", "建立场景",
            "渲染气氛", "表现情绪", "tbd", "TBD", "todo", "TODO",
        }
        missing_purpose: list[str] = []
        vague_purpose: list[str] = []
        for s in self.shots:
            if not s.narrative_purpose or not s.narrative_purpose.strip():
                missing_purpose.append(s.id)
            elif s.narrative_purpose.strip() in _vague or len(s.narrative_purpose.strip()) < 8:
                vague_purpose.append(s.id)
        if missing_purpose:
            warnings.append(
                f"narrative_purpose missing on {len(missing_purpose)} shot(s): "
                f"{', '.join(missing_purpose[:5])}"
                f"{'...' if len(missing_purpose) > 5 else ''}. "
                f"山音铁律：每个 shot 必填具体叙事目的。"
            )
        if vague_purpose:
            warnings.append(
                f"narrative_purpose too vague on {len(vague_purpose)} shot(s): "
                f"{', '.join(vague_purpose[:5])}"
                f"{'...' if len(vague_purpose) > 5 else ''}. "
                f"要具体到视听手段, 例如 '用低角度仰拍 + 缓慢推近放大钱夫人的优越感'。"
            )

        # First shot cannot chain.
        if self.shots and self.shots[0].use_prev_last_frame_as_first:
            warnings.append(
                f"first shot {self.shots[0].id}: use_prev_last_frame_as_first=true "
                f"but no previous shot exists — set it to false."
            )
        # i2v shots that need a previous frame but the previous shot doesn't chain.
        for s in self.shots:
            if s.kind == "i2v" and not s.use_prev_last_frame_as_first:
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
            if not s.characters and s.kind != "t2v":
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
