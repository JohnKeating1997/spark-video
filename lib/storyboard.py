"""Storyboard schema — provider-agnostic.

Each shot will be turned into one Wan video-synthesis request by
``videogen render``. The shot itself only declares a generic *kind*
(``t2v`` | ``i2v`` | ``r2v``). Mapping to a concrete model name is the
provider's job — see ``scripts/providers/``.

The provider/model contract owns duration: Wan3.0 supports 2..30s while
legacy Wan2.7 supports 2..15s. The provider-agnostic Shot shape therefore
allows up to 30s, and Storyboard validates against ``video_model``. Duration is
required so the Director Agent must choose it from content rather than inherit
a preset. Shots longer than 15s require an explicit timed beat plan.

Backward-compat: if ``Shot`` JSON still carries the old ``model`` field
with a ``wan2.7-*`` literal, we transparently
translate it to the new ``kind`` field on validate.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from lib.cinematic import cinematic_budget
from lib.prompt_compiler import VisualMedium, require_visual_medium


def _is_cjk_char(ch: str) -> bool:
    o = ord(ch)
    return (
        0x4E00 <= o <= 0x9FFF
        or 0x3400 <= o <= 0x4DBF
        or 0x20000 <= o <= 0x2A6DF
        or 0x3000 <= o <= 0x303F
    )


def estimate_narration_audio_seconds(
    text: str,
    *,
    speech_rate: float | None = None,
) -> float:
    """Heuristic wall-clock seconds for narration audio after speech_rate.

    Used by Storyboard's validation pass to warn when a narration shot's
    duration is way under the TTS length.
    """
    import os
    rate = speech_rate if speech_rate is not None else float(
        os.environ.get("SPARK_VIDEO_NARRATOR_SPEECH_RATE", "1.2")
    )
    rate = max(0.05, float(rate))
    s = (text or "").strip()
    if not s:
        return 0.0
    cjk = sum(1 for ch in s if _is_cjk_char(ch))
    non_cjk = max(0, len(s) - cjk)
    natural_sec = max(0.35, cjk / 3.0 + non_cjk / 12.0)
    return natural_sec / rate


ShotKind = Literal["t2v", "i2v", "r2v"]
AnimaticStyle = VisualMedium
ProviderName = Literal["wan-cli"]
PROVIDER_ALIASES = {
    "wan": "wan-cli",
}

ShotGroupRole = Literal[
    "establish",
    "progression",
    "reaction",
    "contrast",
    "resolution",
]
_SHOT_GROUP_ROLE_ALIASES = {
    "establish": "establish",
    "progress": "progression",
    "progression": "progression",
    "reaction": "reaction",
    "contrast": "contrast",
    "close": "resolution",
    "closure": "resolution",
    "resolution": "resolution",
    # Legacy Chinese storyboard values. Unicode escapes keep the schema and
    # generated documentation English-only while preserving read compatibility.
    "\u5efa\u7acb": "establish",
    "\u9012\u8fdb": "progression",
    "\u53cd\u5e94": "reaction",
    "\u5bf9\u6bd4": "contrast",
    "\u6536\u5c3e": "resolution",
}

_VAGUE_NARRATIVE_PURPOSES = {
    "",
    "show conflict",
    "advance the plot",
    "advance plot",
    "move the story forward",
    "establish the scene",
    "build atmosphere",
    "show emotion",
    "tbd",
    "todo",
    # Match legacy Chinese content without making Chinese the canonical output.
    "\u5c55\u73b0\u51b2\u7a81",
    "\u63a8\u8fdb\u5267\u60c5",
    "\u63a8\u8fdb\u6545\u4e8b",
    "\u5efa\u7acb\u573a\u666f",
    "\u6e32\u67d3\u6c14\u6c1b",
    "\u8868\u73b0\u60c5\u7eea",
}

# Episode-level story format only. Audio source is owned independently by
# ``AudioPlan``; legacy role/narration fields are migrated for compatibility.
EpisodeMode = Literal["drama", "narration"]
VideoModel = Literal["wan3.0", "wan2.7"]
AudioMode = Literal["presenter_voiceover", "native_dialogue", "hybrid"]
ModelAudioPolicy = Literal["strip_all", "keep", "per_shot"]
SubtitleMode = Literal["off", "post"]
SpeechSource = Literal["post_tts", "model", "none"]
VisualSpeechMode = Literal["voiceover", "on_camera", "none"]

# Per-shot role. In drama-mode storyboards every shot must be ``drama``.
# In narration-mode storyboards a shot can be either ``narration`` (TTS
# post-pass replaces audio) or ``drama`` (the regular long-form path).
ShotRole = Literal["drama", "narration"]
TransitionType = Literal[
    "continuous_action",
    "match_action",
    "shot_reverse_shot",
    "same_scene_cut",
    "establishing_cut",
    "time_or_location_jump",
    "montage",
    "hard_cut",
]

# Per-kind worst-case duration ceiling. Provider-specific ceilings live on
# the provider class itself; this is the schema-level fallback.
ABSOLUTE_MAX_DURATION = 30
DURATION_FLOOR = 2

# Legacy provider-specific model strings that may still appear in old
# ``storyboard.json`` files. Mapped to (kind, provider) on read so the
# whole pipeline keeps working without manual migration.
LEGACY_MODEL_TO_KIND: dict[str, tuple[ShotKind, ProviderName]] = {
    "wan2.7-r2v":              ("r2v", "wan-cli"),
    "wan2.7-i2v-2026-04-25":   ("i2v", "wan-cli"),
    "wan2.7-t2v-2026-04-25":   ("t2v", "wan-cli"),
}


class ShotBeat(BaseModel):
    start_s: int = Field(ge=0)
    end_s: int = Field(gt=0)
    action: str = Field(min_length=1)


class ShotTransition(BaseModel):
    """Selective visual relationship between this shot and its predecessor."""

    type: TransitionType
    preserve: list[str] = Field(default_factory=list)
    allow_change: list[str] = Field(default_factory=list)

    @field_validator("preserve", "allow_change")
    @classmethod
    def _normalize_attributes(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            item = str(value).strip()
            if item and item not in normalized:
                normalized.append(item)
        return normalized

    @model_validator(mode="after")
    def _attributes_do_not_conflict(self) -> "ShotTransition":
        overlap = set(self.preserve) & set(self.allow_change)
        if overlap:
            raise ValueError(
                "transition attributes cannot be both preserved and allowed "
                f"to change: {', '.join(sorted(overlap))}"
            )
        return self


class Shot(BaseModel):
    id: str = Field(description="shot id, e.g. 'S01-001' (scene-shot)")
    scene: str = Field(description="logical scene id, e.g. 'S01'")
    duration: int = Field(
        ...,
        ge=DURATION_FLOOR,
        le=ABSOLUTE_MAX_DURATION,
        description=(
            "Agent-selected integer seconds. Choose the shortest duration that "
            "fits the content. Wan3.0 supports up to 30; legacy Wan2.7 is "
            "limited to 15 and is validated at Storyboard level."
        ),
    )
    prompt: str = Field(description="visual action prompt — performance, lighting, and atmosphere")
    camera_path: str | None = Field(
        default=None,
        description=(
            "Explicit camera trajectory from opening framing through movement "
            "to the final camera position. Keep separate from subject action."
        ),
    )
    end_composition: str | None = Field(
        default=None,
        description=(
            "The intended final-frame composition: subject placement, scale, "
            "gaze/action state, foreground/background, and visual handoff."
        ),
    )
    animatic_prompt: str | None = Field(
        default=None,
        description=(
            "Optional static storyboard / animatic panel prompt. If omitted, "
            "storyboard.py animatic derives a still-frame panel from ``prompt``. "
            "Use this when the moving-video prompt contains audio or motion "
            "instructions that should be simplified for a comic-style preview."
        ),
    )
    animatic_style: AnimaticStyle | None = Field(
        default=None,
        description=(
            "Optional static-preview medium override: live_action, "
            "2d_animation, 3d_animation, stop_motion, or mixed. Mixed shots "
            "must define each element's medium explicitly in animatic_prompt."
        ),
    )
    negative_prompt: str | None = Field(
        default=None,
        description=(
            "Optional negative prompt. Providers may translate recognized "
            "quality terms into safe positive guidance; unsupported or "
            "sensitive terms are not forwarded verbatim."
        ),
    )

    # ── Shanyin fusion ──────────────────────────────────────────
    # Why this shot exists in the story. Specific to visual means
    # (e.g. "low-angle push-in to amplify Madam Quinn's superiority"), not vague labels
    # (e.g. "show conflict"). The CLI doesn't render this — it's metadata for
    # the director's own discipline + VFX reviewer's quality gate.
    narrative_purpose: str | None = Field(
        default=None,
        description=(
            "Shanyin fusion: required on every shot. Be specific about "
            "audiovisual means; avoid empty labels like 'show conflict'."
        ),
    )
    # Optional shot-group affiliation (Shanyin "shot group" concept). Shots
    # in the same group jointly complete one narrative unit (montage /
    # progression / cause-effect / contrast group).
    shot_group_id: str | None = Field(default=None, description="e.g. 'G01'")
    shot_group_role: ShotGroupRole | None = None
    # ──────────────────────────────────────────────────────

    # Character references — names must match cast.json
    characters: list[str] = Field(default_factory=list, description="cast names featured")

    # Key-prop references — names must match props.json. Each prop's
    # reference_image is appended to media[] for r2v shots, after cast
    # cast references and after the scene's set image. Empty list = no prop
    # locking for this shot. The director SKILL forbids re-mentioning
    # the prop's appearance in the prompt — the reference image owns it.
    props: list[str] = Field(
        default_factory=list,
        description=(
            "Key-prop names featured in this shot. Names must match a "
            "folder under projects/<id>/props/<name>/ or "
            "projects/<id>/<episode>/props/<name>/. The renderer "
            "appends each prop's reference image to r2v shots; t2v / "
            "i2v shots ignore this field (no media slot)."
        ),
    )

    # Continuity
    transition_from_previous: ShotTransition | None = Field(
        default=None,
        description=(
            "Director-selected relationship to the preceding shot. Only "
            "continuous_action uses the preceding final frame as this shot's "
            "first frame; other types preserve only the declared attributes."
        ),
    )
    use_prev_last_frame_as_first: bool = Field(
        default=True,
        description="If true, ffmpeg extracts last frame of previous successful shot and feeds as first_frame.",
    )

    kind: ShotKind = Field(
        default="r2v",
        description=(
            "Generic shot kind. The active provider maps "
            "this to a concrete model name at render time. Choose r2v for "
            "character-driven shots with cast references, t2v for "
            "establishing shots with no cast lock, i2v for first-frame "
            "continuation within a chain group."
        ),
    )

    seed: int | None = None
    candidates: int = Field(default=1, ge=1, le=4, description="N candidate renders per shot")

    set_id: str | None = Field(
        default=None,
        description=(
            "Per-shot movie-set override. Falls back to "
            "``Scene.set_id`` when omitted. Use this when one logical "
            "scene legitimately spans multiple location/lighting states "
            "(common in narration mode: construction-site-night → wedding-car-day → hotel-dusk are "
            "three beats inside one scene, each needs its own set image). "
            "**One set folder = one lighting state**: never reuse a "
            "daytime inn set for a nighttime inn shot — scaffold a second set "
            "instead. Setting set_id to empty string ('') explicitly "
            "disables the fallback for this shot."
        ),
    )

    # ── legacy narration compatibility ───────────────────────────────────
    role: ShotRole = Field(
        default="drama",
        description=(
            "Legacy shot role used only to migrate old storyboards. New "
            "storyboards must choose speech_source from the episode AudioPlan."
        ),
    )
    narration_text: str | None = Field(
        default=None,
        description=(
            "Legacy narration text. New storyboards use speech_text."
        ),
    )
    narrator_voice: str | None = Field(
        default=None,
        description=(
            "Legacy hybrid-only voice override. Presenter voiceover forbids "
            "per-shot voice changes."
        ),
    )
    speech_source: SpeechSource | None = Field(
        default=None,
        description="Explicit audio source. Legacy role fields are migrated automatically.",
    )
    speaker: str | None = None
    speech_text: str | None = None
    visual_speech_mode: VisualSpeechMode = "none"
    allow_generated_text: bool = False
    long_take_reason: str | None = Field(
        default=None,
        description=(
            "Required only above 15s: explain why the shot is an indivisible "
            "continuous event and why cutting would damage the intended result."
        ),
    )
    beats: list[ShotBeat] = Field(
        default_factory=list,
        description=(
            "Optional timed action plan for precise continuous choreography; "
            "required above 15s. Short shots may use a few causally linked "
            "micro-phases when contact, occlusion, environmental response, or "
            "camera/subject synchronization needs explicit timing. Entry count "
            "is always chosen from content rather than a duration-based quota."
        ),
    )
    # ──────────────────────────────────────────────────────────────────────

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_model(cls, data: Any) -> Any:
        """Translate a legacy ``model: "wan2.7-*"`` value to ``kind``.

        Old storyboards predate the provider abstraction — they wrote out
        the concrete model name directly. We accept those silently so users
        don't have to hand-edit storyboard.json.
        """
        if not isinstance(data, dict):
            return data
        data = dict(data)
        transition = data.get("transition_from_previous")
        if isinstance(transition, dict) and transition.get("type"):
            data["use_prev_last_frame_as_first"] = (
                transition.get("type") == "continuous_action"
            )
        if data.get("animatic_style") is not None:
            data["animatic_style"] = require_visual_medium(
                data["animatic_style"], field="animatic_style"
            )
        role = data.get("role", "drama")
        if not data.get("speech_source"):
            data["speech_source"] = "post_tts" if role == "narration" else "model"
        if not data.get("speech_text") and data.get("narration_text"):
            data["speech_text"] = data["narration_text"]
        if data.get("speech_source") == "post_tts" and not data.get("visual_speech_mode"):
            data["visual_speech_mode"] = "voiceover"
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

    @field_validator("shot_group_role", mode="before")
    @classmethod
    def _normalize_shot_group_role(cls, value: Any) -> Any:
        """Normalize English aliases and legacy localized input."""
        if value is None:
            return None
        normalized = str(value).strip().casefold()
        return _SHOT_GROUP_ROLE_ALIASES.get(normalized, normalized)

    @model_validator(mode="after")
    def _check_narration_fields(self) -> "Shot":
        if self.role == "narration":
            if not (self.narration_text or self.speech_text or "").strip():
                raise ValueError(
                    f"shot {self.id}: role='narration' requires "
                    f"non-empty narration_text or speech_text"
                )
        else:
            # drama role must not carry narration metadata.
            if self.narration_text:
                raise ValueError(
                    f"shot {self.id}: role='drama' must not set "
                    f"narration_text (only narration-role shots get the "
                    f"TTS post-pass)"
                )
        if self.speech_source == "post_tts" and not (self.speech_text or "").strip():
            raise ValueError(
                f"shot {self.id}: speech_source='post_tts' requires speech_text"
            )
        if self.speech_source == "none" and (self.speech_text or "").strip():
            raise ValueError(
                f"shot {self.id}: speech_source='none' must not set speech_text"
            )
        if self.duration > 15:
            if not (self.long_take_reason or "").strip():
                raise ValueError(
                    f"shot {self.id}: {self.duration}s is an exceptional long "
                    f"take and requires long_take_reason"
                )
            if not self.beats:
                raise ValueError(
                    f"shot {self.id}: {self.duration}s exceptional long take "
                    f"requires a timed action plan; beat count is content-driven"
                )
        if self.beats:
            if self.beats[0].start_s != 0 or self.beats[-1].end_s != self.duration:
                raise ValueError(
                    f"shot {self.id}: beats must span exactly 0-{self.duration}s"
                )
            for previous, current in zip(self.beats, self.beats[1:]):
                if previous.end_s != current.start_s:
                    raise ValueError(
                        f"shot {self.id}: beats must be contiguous and non-overlapping"
                    )
        return self


class Scene(BaseModel):
    """A logical scene — one location + time + situation.

    The director defines all scenes BEFORE writing individual shots.
    Every shot in a scene inherits its environment description, ensuring
    visual consistency even though the video model has no memory.
    """
    id: str = Field(description="scene id, e.g. 'S01'. Must match shot.scene references.")
    name: str = Field(description="short human label, e.g. 'riverstone-stage-day'")
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
    props_present: list[str] = Field(
        default_factory=list,
        description=(
            "All key props that appear at some point in this scene "
            "(for recall — mirrors characters_present). The validate "
            "step warns when shots reference props not listed here."
        ),
    )
    bgm_track: str | None = Field(
        default=None,
        description=(
            "Optional BGM track name (matches a file under "
            "``projects/<id>/bgm/`` or ``projects/<id>/<episode>/bgm/``, "
            "without extension). Only used when ``Storyboard.bgm.mode == "
            "'scene'`` — the stitcher mixes this track underneath every "
            "clip in this scene at ``Storyboard.bgm.volume``. Director "
            "picks the track based on the scene's emotional beat (sentimental "
            "→ slow piano, thriller → low drone, light comedy → upbeat ukulele, …). "
            "Leave null to skip BGM on this scene."
        ),
    )
    set_id: str | None = Field(
        default=None,
        description=(
            "Optional movie-set name (matches a folder under "
            "``projects/<id>/movie-set/<name>/`` or "
            "``projects/<id>/<episode>/movie-set/<name>/``). When set, the "
            "renderer appends that set's reference image to every r2v shot "
            "in this scene, locking the location's appearance the same way "
            "cast reference images lock characters. t2v shots can't take a "
            "reference image — for those, the director should still weave "
            "the set's textual description into the prompt."
        ),
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


BGMMode = Literal["off", "global", "scene"]


class BGMConfig(BaseModel):
    """Background music configuration for one episode.

    Populated by the producer at GATE 0.5 (``/episode``) after a BGM
    folder is detected under ``projects/<id>/bgm/`` or
    ``projects/<id>/<episode>/bgm/``. The renderer reads
    ``forbid_model_bgm`` to inject a no-music directive into every shot
    prompt; the stitcher reads ``mode`` + ``track`` (+ per-scene
    ``Scene.bgm_track``) to mix audio onto the final concatenated MP4.

    Modes:

    * ``off`` — BGM detected but the user opted not to use it. We still
      keep the entry around so the producer doesn't re-ask on rerun.
    * ``global`` — one track plays under the entire final video. The
      track filename (stem) lives in ``track``.
    * ``scene`` — per-scene assignment. The director writes
      ``Scene.bgm_track`` on each scene that should carry BGM; scenes
      with ``bgm_track=None`` stay silent (no BGM under those clips).
      ``track`` is ignored in this mode.
    """

    enabled: bool = Field(
        default=False,
        description=(
            "Master switch. False when the user explicitly skips BGM or "
            "no BGM folder was found. When False the stitcher does not "
            "mix any music; ``forbid_model_bgm`` is still honoured "
            "(useful when the user has no BGM file yet but still wants "
            "clean clips for later mixing in a DAW)."
        ),
    )
    mode: BGMMode = Field(
        default="off",
        description=(
            "How to apply BGM. ``off`` | ``global`` (one track for the "
            "whole video) | ``scene`` (per-scene via ``Scene.bgm_track``)."
        ),
    )
    forbid_model_bgm: bool = Field(
        default=True,
        description=(
            "When True the renderer appends a 'no BGM / no soundtrack' "
            "directive to every shot prompt (and to negative_prompt on "
            "providers that support it) so the video model doesn't "
            "generate competing music that would fight the stitched "
            "BGM. Defaults to True for ordinary short shots because "
            "independently generated clip music cannot form a coherent "
            "program-level score. Exceptional shots above 15s may retain "
            "Wan's native music when no program-level BGM is enabled. Independent "
            "of ``enabled`` — you can forbid model music even when not "
            "stitching your own BGM (clean clips for later mixing)."
        ),
    )
    track: str | None = Field(
        default=None,
        description=(
            "Track name (filename stem, no extension) used in ``global`` "
            "mode. Must resolve under ``projects/<id>/bgm/`` or "
            "``projects/<id>/<episode>/bgm/``. Ignored in ``scene`` mode."
        ),
    )
    volume: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description=(
            "Linear gain applied to the BGM stream before mixing with "
            "the (dialog) audio of each clip. 0.25 ≈ underscore. "
            "Use 0.0 to silence (debug)."
        ),
    )
    fade_in_s: float = Field(
        default=0.5,
        ge=0.0,
        le=10.0,
        description=(
            "Fade-in duration applied to the program-level BGM track in "
            "seconds. Defaults to a quick 0.5s entrance."
        ),
    )
    fade_out_s: float = Field(
        default=2.0,
        ge=0.0,
        le=10.0,
        description=(
            "Fade-out duration applied to the program-level BGM track in "
            "seconds. Defaults to a smooth 2s ending."
        ),
    )


class AudioPlan(BaseModel):
    """Episode-wide voice identity and source policy approved at GATE 0."""

    mode: AudioMode
    presenter: str | None = None
    voice: str | None = None
    model_audio_policy: ModelAudioPolicy
    subtitle_mode: SubtitleMode = "off"

    @model_validator(mode="after")
    def _check_mode_contract(self) -> "AudioPlan":
        if self.mode == "presenter_voiceover":
            if not self.presenter or not self.voice:
                raise ValueError(
                    "presenter_voiceover requires both presenter and voice"
                )
            if self.model_audio_policy != "strip_all":
                raise ValueError(
                    "presenter_voiceover requires model_audio_policy='strip_all'"
                )
        elif self.mode == "native_dialogue" and self.model_audio_policy != "keep":
            raise ValueError("native_dialogue requires model_audio_policy='keep'")
        elif self.mode == "hybrid" and self.model_audio_policy != "per_shot":
            raise ValueError("hybrid requires model_audio_policy='per_shot'")
        return self


class Storyboard(BaseModel):
    project_id: str | None = None
    title: str
    synopsis: str | None = None
    target_duration_s: int = Field(
        default=180,
        ge=2,
        description="user's intended final duration; enforced at GATE 4",
    )
    resolution: str = "720P"
    ratio: str = "16:9"
    provider: ProviderName | None = Field(
        default=None,
        description=(
            "Video provider for this episode (wan-cli). When absent, "
            "the renderer falls back to the SPARK_VIDEO_PROVIDER env var, then "
            "the built-in default (wan-cli)."
        ),
    )
    video_model: VideoModel = "wan3.0"
    mode: EpisodeMode = Field(
        default="drama",
        description=(
            "Story structure only: drama stages action/conflict; narration "
            "organizes explanatory beats. Audio still follows AudioPlan."
        ),
    )
    narrator_voice: str | None = Field(
        default=None,
        description=(
            "Legacy episode voice. New presenter voiceover uses AudioPlan.voice."
        ),
    )
    audio: AudioPlan
    scenes: list[Scene] = Field(
        default_factory=list,
        description=(
            "Explicit scene definitions. Each scene carries a detailed environment "
            "description that MUST be woven into every shot in that scene. "
            "If empty (legacy), shots still work but lose scene-level consistency."
        ),
    )
    bgm: BGMConfig | None = Field(
        default=None,
        description=(
            "Background music configuration. Set by the producer at "
            "``/episode`` GATE 0.5 when a ``bgm/`` folder is detected. "
            "When ``None``, the stitcher does not mix any BGM and the "
            "renderer still forbids clip-local model music by default."
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
        data = dict(data)
        if not data.get("audio"):
            mode = data.get("mode", "drama")
            narrator_voice = data.get("narrator_voice")
            data["audio"] = (
                {
                    "mode": "hybrid",
                    "presenter": None,
                    "voice": narrator_voice,
                    "model_audio_policy": "per_shot",
                    "subtitle_mode": "off",
                }
                if mode == "narration"
                else {
                    "mode": "native_dialogue",
                    "presenter": None,
                    "voice": None,
                    "model_audio_policy": "keep",
                    "subtitle_mode": "off",
                }
            )
        if data.get("provider"):
            provider = str(data["provider"]).strip().lower()
            data["provider"] = PROVIDER_ALIASES.get(provider, provider)
            return data
        for shot in data.get("shots") or []:
            if isinstance(shot, dict) and shot.get("model"):
                mapping = LEGACY_MODEL_TO_KIND.get(str(shot["model"]))
                if mapping:
                    data["provider"] = mapping[1]
                    break
        return data

    @model_validator(mode="after")
    def _check_bgm_consistency(self) -> "Storyboard":
        bgm = self.bgm
        if bgm is None:
            return self
        if bgm.mode == "global" and bgm.enabled and not bgm.track:
            raise ValueError(
                "storyboard.bgm.mode='global' but bgm.track is empty — "
                "set bgm.track to a filename (without extension) that "
                "exists under projects/<id>/bgm/ or "
                "projects/<id>/<episode>/bgm/, or switch the mode."
            )
        if bgm.mode == "scene" and bgm.enabled:
            tagged = [s.id for s in self.scenes if s.bgm_track]
            if not tagged:
                raise ValueError(
                    "storyboard.bgm.mode='scene' but no scene has "
                    "bgm_track set — either tag at least one Scene with "
                    "bgm_track=<track-name>, switch to mode='global', "
                    "or disable BGM (enabled=false)."
                )
        return self

    @model_validator(mode="after")
    def _check_mode_role_consistency(self) -> "Storyboard":
        if self.mode == "drama":
            bad = [s.id for s in self.shots if s.role == "narration"]
            if bad:
                raise ValueError(
                    f"storyboard.mode='drama' but {len(bad)} shot(s) have "
                    f"role='narration': {', '.join(bad[:5])}"
                    f"{'…' if len(bad) > 5 else ''}. "
                    f"Either change those shots to role='drama' (and clear "
                    f"narration_text) or set storyboard.mode='narration'."
                )
        limit = 30 if self.video_model == "wan3.0" else 15
        too_long = [s.id for s in self.shots if s.duration > limit]
        if too_long:
            raise ValueError(
                f"storyboard.video_model={self.video_model!r} supports at most "
                f"{limit}s; over-limit shots: {', '.join(too_long[:8])}"
            )

        audio = self.audio
        if audio.mode == "presenter_voiceover":
            non_tts = [s.id for s in self.shots if s.speech_source != "post_tts"]
            if non_tts:
                raise ValueError(
                    "presenter_voiceover requires post_tts on every shot; "
                    f"offenders: {', '.join(non_tts[:8])}"
                )
            wrong_speaker = [
                s.id for s in self.shots
                if s.speech_source == "post_tts" and s.speaker != audio.presenter
            ]
            if wrong_speaker:
                raise ValueError(
                    f"presenter_voiceover requires speaker={audio.presenter!r}: "
                    f"{', '.join(wrong_speaker[:8])}"
                )
            wrong_voice = [
                s.id for s in self.shots
                if s.speech_source == "post_tts"
                and s.narrator_voice
                and s.narrator_voice != audio.voice
            ]
            if wrong_voice:
                raise ValueError(
                    "presenter_voiceover forbids per-shot voice changes: "
                    + ", ".join(wrong_voice[:8])
                )
        elif audio.mode == "native_dialogue":
            post_tts = [s.id for s in self.shots if s.speech_source == "post_tts"]
            if post_tts:
                raise ValueError(
                    "native_dialogue forbids post_tts shots: "
                    + ", ".join(post_tts[:8])
                )
        return self

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

        # Shanyin fusion: every shot should have a non-trivial narrative_purpose.
        # Soft warning only — never blocks render. VFX reviewer enforces.
        missing_purpose: list[str] = []
        vague_purpose: list[str] = []
        for s in self.shots:
            if not s.narrative_purpose or not s.narrative_purpose.strip():
                missing_purpose.append(s.id)
            else:
                purpose = s.narrative_purpose.strip()
                if purpose.casefold() in _VAGUE_NARRATIVE_PURPOSES or len(purpose) < 8:
                    vague_purpose.append(s.id)
        if missing_purpose:
            warnings.append(
                f"narrative_purpose missing on {len(missing_purpose)} shot(s): "
                f"{', '.join(missing_purpose[:5])}"
                f"{'...' if len(missing_purpose) > 5 else ''}. "
                f"Shanyin rule: every shot must have a specific narrative purpose."
            )
        if vague_purpose:
            warnings.append(
                f"narrative_purpose too vague on {len(vague_purpose)} shot(s): "
                f"{', '.join(vague_purpose[:5])}"
                f"{'...' if len(vague_purpose) > 5 else ''}. "
                f"Be specific about audiovisual means, e.g. "
                f"'low-angle push-in to amplify Madam Quinn's superiority'."
            )

        missing_camera_path = [s.id for s in self.shots if not (s.camera_path or "").strip()]
        missing_end_composition = [
            s.id for s in self.shots if not (s.end_composition or "").strip()
        ]
        if missing_camera_path:
            warnings.append(
                "camera_path missing on shot(s): "
                + ", ".join(missing_camera_path[:5])
                + ("..." if len(missing_camera_path) > 5 else "")
                + ". New storyboards should declare an explicit camera trajectory."
            )
        if missing_end_composition:
            warnings.append(
                "end_composition missing on shot(s): "
                + ", ".join(missing_end_composition[:5])
                + ("..." if len(missing_end_composition) > 5 else "")
                + ". New storyboards should lock the final-frame handoff."
            )

        exceptional = [s.id for s in self.shots if s.duration > 15]
        if exceptional:
            warnings.append(
                "exceptional long takes require explicit creative review: "
                + ", ".join(exceptional[:5])
                + ("..." if len(exceptional) > 5 else "")
                + ". Confirm each cannot be expressed as shorter shots."
            )

        # Post-TTS recommendations (soft — never block render).
        if self.mode == "narration" or self.audio.mode == "presenter_voiceover":
            for s in self.shots:
                if s.speech_source != "post_tts":
                    continue
                if s.use_prev_last_frame_as_first:
                    warnings.append(
                        f"{s.id}: narration shot has "
                        f"use_prev_last_frame_as_first=true — narration "
                        f"shots should break the chain (false) so they "
                        f"render in parallel."
                    )
                if not (6 <= s.duration <= 15):
                    warnings.append(
                        f"{s.id}: post-TTS shot duration {s.duration}s "
                        f"out of recommended 6-15s; size it to estimated "
                        f"speech duration plus 0.5-1.0s."
                    )
                speech_text = s.speech_text or s.narration_text
                if speech_text:
                    est = estimate_narration_audio_seconds(speech_text)
                    if est > float(s.duration) + 0.55:
                        warnings.append(
                            f"{s.id}: speech_text may run ~{est:.1f}s (heuristic) "
                            f"after default speech-rate post-process, but shot "
                            f"duration is {s.duration}s — rendered picture may "
                            f"freeze on the last frame while audio finishes. "
                            f"Shorten the line, raise duration, or split the beat."
                        )
        elif self.narrator_voice and self.audio.mode == "native_dialogue":
            warnings.append(
                "narrator_voice set but mode='drama' — value will be "
                "ignored. Switch to mode='narration' to enable TTS."
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

        # set_id sanity — scenes that name a set but no shot in that scene
        # is r2v get a warning (set reference image only attaches to r2v).
        scene_lookup = self.scene_map()
        for sc in self.scenes:
            if not sc.set_id:
                continue
            r2v_in_scene = [
                s for s in self.shots
                if s.scene == sc.id and s.kind == "r2v"
                and _effective_set(s, sc) == sc.set_id
            ]
            if not r2v_in_scene:
                warnings.append(
                    f"scene {sc.id} declares set_id={sc.set_id!r} but no "
                    f"r2v shot inherits it (every r2v shot in this scene "
                    f"either overrides set_id or is t2v/i2v). The scene's "
                    f"set reference image will never attach — drop "
                    f"Scene.set_id, or remove the per-shot overrides."
                )

        # Lighting consistency rule — within ONE chain group, every r2v shot must
        # resolve to the SAME effective set_id (or no set at all).
        # Mixing inn-day + inn-night inside one chain produces a
        # discontinuous lighting flicker (the chained first_frame is
        # already locked to the previous shot's lighting, but the new
        # set image fights it). Splits between chain groups are fine —
        # those are independent chain groups by definition.
        cur_chain_set: tuple[str, str | None] | None = None  # (first_shot_id, set_id)
        for s in self.shots:
            sc = scene_lookup.get(s.scene)
            eff = _effective_set(s, sc)
            starts_new_chain = (
                cur_chain_set is None or not s.use_prev_last_frame_as_first
            )
            if starts_new_chain:
                cur_chain_set = (s.id, eff if s.kind == "r2v" else None)
            else:
                if s.kind != "r2v":
                    continue
                anchor_shot, anchor_set = cur_chain_set
                if anchor_set is None:
                    # First r2v in this chain sets the anchor.
                    cur_chain_set = (anchor_shot, eff)
                elif eff != anchor_set:
                    warnings.append(
                        f"{s.id}: chain rooted at {anchor_shot} uses "
                        f"set_id={anchor_set!r} but this shot resolves to "
                        f"set_id={eff!r}. Within one chain group every "
                        f"r2v shot must share the same set (lighting / "
                        f"color grade / time of day must match). Split the chain "
                        f"(use_prev_last_frame_as_first=false on this shot) "
                        f"or align the set_id."
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
                if sc and s.props:
                    missing_props = set(s.props) - set(sc.props_present)
                    if missing_props:
                        warnings.append(
                            f"{s.id}: props {missing_props} appear in shot but not in "
                            f"scene {sc.id}.props_present — add them for recall."
                        )

        # Props on non-r2v shots have no effect — the renderer can't
        # attach reference_image to t2v/i2v media[]. Soft warn.
        for s in self.shots:
            if s.props and s.kind != "r2v":
                warnings.append(
                    f"{s.id}: kind={s.kind} cannot accept prop reference "
                    f"images (only r2v has media[reference_image]). Either "
                    f"change kind to r2v or move the prop description into "
                    f"the prompt manually."
                )

        return warnings


# Public helper — also used by render-time providers via their own copies
# (kept duplicated there to avoid circular imports in the hot path).
def _effective_set(shot: Shot, scene: Scene | None) -> str | None:
    """Resolve set_id for one shot, honouring per-shot override:

      shot.set_id is None  → inherit scene.set_id
      shot.set_id == ""    → explicit opt-out (no set, even if scene has one)
      shot.set_id == "x"   → use 'x' regardless of scene.set_id
    """
    if shot.set_id is not None:
        return shot.set_id or None
    if scene is None:
        return None
    return scene.set_id or None
