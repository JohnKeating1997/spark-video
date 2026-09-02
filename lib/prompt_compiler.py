"""Shared deterministic rules for visual prompt compilation.

Creative agents author shot/asset intent.  This module owns the stable parts:
visual-medium precedence, compatible project art direction, and localized Wan
reference tags.  Keep provider calls and creative rewriting out of this file.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, Mapping, Sequence, TypeAlias

VisualMedium: TypeAlias = Literal[
    "live_action",
    "2d_animation",
    "3d_animation",
    "stop_motion",
    "mixed",
]
VALID_VISUAL_MEDIA = {
    "live_action",
    "2d_animation",
    "3d_animation",
    "stop_motion",
    "mixed",
}
LEGACY_VISUAL_MEDIA = {"illustration"}

_MEDIUM_ALIASES = {
    "live_action": "live_action",
    "live-action": "live_action",
    "live action": "live_action",
    "photoreal": "live_action",
    "photorealistic": "live_action",
    "2d_animation": "2d_animation",
    "2d-animation": "2d_animation",
    "2d animation": "2d_animation",
    "illustration": "2d_animation",
    "illustrated": "2d_animation",
    "cartoon": "2d_animation",
    "anime": "2d_animation",
    "cel_animation": "2d_animation",
    "cel-animation": "2d_animation",
    "cel animation": "2d_animation",
    "3d_animation": "3d_animation",
    "3d-animation": "3d_animation",
    "3d animation": "3d_animation",
    "cgi": "3d_animation",
    "computer_generated": "3d_animation",
    "computer-generated": "3d_animation",
    "stop_motion": "stop_motion",
    "stop-motion": "stop_motion",
    "stop motion": "stop_motion",
    "claymation": "stop_motion",
    "mixed": "mixed",
    "hybrid": "mixed",
}
LIVE_MARKERS = (
    "真人", "写实", "实拍", "live action", "live-action", "photoreal",
    "realistic", "realistically rendered",
)
TWO_D_MARKERS = (
    "二维动画", "2d动画", "插画", "卡通", "贴纸", "赛璐璐", "手绘动画",
    "2d animation", "2d-animation", "illustration", "illustrated", "cartoon",
    "anime", "sticker", "cel animation", "cel-animation", "hand-drawn animation",
)
THREE_D_MARKERS = (
    "三维动画", "3d动画", "三维cg", "3d cg", "3d animation", "3d-animation",
    "cgi", "computer-generated", "computer generated", "stylized cg",
    "cinematic cg",
)
STOP_MOTION_MARKERS = (
    "定格动画", "黏土动画", "木偶动画", "stop motion", "stop-motion",
    "claymation", "puppet animation",
)

_MEDIUM_MARKERS: dict[VisualMedium, tuple[str, ...]] = {
    "live_action": LIVE_MARKERS,
    "2d_animation": TWO_D_MARKERS,
    "3d_animation": THREE_D_MARKERS,
    "stop_motion": STOP_MOTION_MARKERS,
    "mixed": (),
}


def normalize_visual_medium(value: object) -> VisualMedium | None:
    return _MEDIUM_ALIASES.get(str(value or "").strip().lower())  # type: ignore[return-value]


def require_visual_medium(value: object, *, field: str = "visual_medium") -> VisualMedium:
    """Normalize a declared medium or reject ambiguous/unknown values."""
    medium = normalize_visual_medium(value)
    if medium:
        return medium
    raw = str(value or "").strip()
    if raw.lower() in {"animation", "animated", "动画"}:
        raise ValueError(
            f"{field}={raw!r} is ambiguous; choose 2d_animation, "
            "3d_animation, or stop_motion"
        )
    raise ValueError(
        f"unknown {field}={raw!r}; expected one of {sorted(VALID_VISUAL_MEDIA)}"
    )


def _media_marked_in(text: str) -> set[VisualMedium]:
    lowered = text.lower()
    return {
        medium
        for medium, markers in _MEDIUM_MARKERS.items()
        if markers and any(marker in lowered for marker in markers)
    }


def infer_visual_medium(text: str) -> VisualMedium:
    marked = _media_marked_in(text)
    if len(marked) > 1:
        return "mixed"
    if marked:
        return next(iter(marked))
    # Backward-compatible fallback for legacy prompts with no explicit medium.
    # New projects should always declare lore.visual_medium.
    return "2d_animation"


def resolve_visual_medium(
    *,
    project_default: object = None,
    shot_overrides: Sequence[object] = (),
    fallback_text: str = "",
) -> VisualMedium:
    declared = {
        require_visual_medium(value, field="animatic_style")
        for value in shot_overrides
        if value is not None and str(value).strip()
    }
    if len(declared) > 1:
        raise ValueError(f"conflicting visual-medium overrides: {sorted(declared)}")
    if declared:
        return next(iter(declared))
    project = (
        require_visual_medium(project_default)
        if project_default is not None and str(project_default).strip()
        else None
    )
    return project or infer_visual_medium(fallback_text)


def style_text_matches_medium(text: str, medium: VisualMedium) -> bool:
    marked = _media_marked_in(text)
    if medium == "mixed":
        # Mixed boundaries are declared locally. Only medium-neutral project
        # prose (lighting, palette, contrast, atmosphere) is safe globally.
        return not marked
    return not marked or marked == {medium}


def art_direction_conflicts(
    lore: Mapping[str, object],
    medium: VisualMedium,
) -> list[str]:
    """Return declared art-direction fields that contradict the medium."""
    conflicts: list[str] = []
    for key in ("visual_style", "camera_language", "mood_anchor"):
        value = str(lore.get(key) or "").strip()
        if not value:
            continue
        marked = _media_marked_in(value)
        if medium == "mixed":
            invalid = bool(marked)
        else:
            invalid = bool(marked - {medium})
        if invalid:
            conflicts.append(
                f"{key} declares {sorted(marked)} but visual_medium is {medium}"
            )
    return conflicts


def require_compatible_art_direction(
    lore: Mapping[str, object],
    medium: VisualMedium,
) -> None:
    conflicts = art_direction_conflicts(lore, medium)
    if conflicts:
        raise ValueError("visual medium conflict: " + "; ".join(conflicts))


def compatible_art_direction(
    lore: Mapping[str, object],
    medium: VisualMedium,
) -> list[str]:
    values: list[str] = []
    for key in ("visual_style", "camera_language", "mood_anchor"):
        value = str(lore.get(key) or "").strip()
        if value and style_text_matches_medium(value, medium):
            values.append(value)
    palette = lore.get("palette")
    if isinstance(palette, list):
        value = ", ".join(str(item).strip() for item in palette if str(item).strip())
    else:
        value = str(palette or "").strip()
    if value:
        values.append(f"palette: {value}")
    return values


def rendering_instruction(medium: VisualMedium, *, language: str = "en") -> str:
    zh = language == "zh"
    table = {
        "live_action": (
            "人物和环境保持真人写实渲染。" if zh
            else "Keep people and the environment realistically rendered."
        ),
        "2d_animation": (
            "整幅画面采用已声明的二维动画或插画风格，并统一线条、造型、上色与阴影语言。" if zh
            else "Render the full frame in the declared 2D animation or illustration style, with consistent linework, shape language, color, and shading."
        ),
        "3d_animation": (
            "整幅画面采用已声明的三维 CG 动画风格，并统一角色建模、材质、灯光与着色语言。" if zh
            else "Render the full frame in the declared 3D CG animation style, with consistent character modeling, materials, lighting, and shading."
        ),
        "stop_motion": (
            "整幅画面采用已声明的定格动画风格，并统一木偶造型、手工材质、布景尺度与逐帧质感。" if zh
            else "Render the full frame in the declared stop-motion style, with consistent puppet design, handcrafted materials, set scale, and frame-by-frame texture."
        ),
        "mixed": (
            "严格遵守镜头明确声明的媒介边界；不要把一种媒介的造型或材质扩散到其他元素。" if zh
            else "Follow the media boundary explicitly declared by the shot; do not spread one medium's shape or material language to other elements."
        ),
    }
    return table[medium]


def reference_treatment_instruction(
    medium: VisualMedium,
    *,
    subject: Literal["character", "location", "prop"],
    language: str = "en",
) -> str:
    """Describe how an authoritative reference should enter this medium."""
    zh = language == "zh"
    preserved = {
        "character": "人物身份与外观" if zh else "character identity and appearance",
        "location": "场景布局与建筑" if zh else "location layout and architecture",
        "prop": "道具设计与材质" if zh else "prop design and materials",
    }[subject]
    treatments = {
        "live_action": "真人写实渲染" if zh else "realistic live-action rendering",
        "2d_animation": "已声明的二维动画或插画语言" if zh else "the declared 2D animation or illustration language",
        "3d_animation": "已声明的三维 CG 建模、材质与着色语言" if zh else "the declared 3D CG modeling, material, and shading language",
        "stop_motion": "已声明的定格动画木偶与手工材质语言" if zh else "the declared stop-motion puppet and handcrafted-material language",
        "mixed": "镜头明确声明的媒介边界" if zh else "the media boundary explicitly declared by the shot",
    }
    if zh:
        return f"保持{preserved}不变，并采用{treatments[medium]}。"
    return f"Preserve {preserved} and use {treatments[medium]}."


def validate_reference_tags(
    prompt: str,
    *,
    tag_prefix: str,
    reference_count: int,
) -> None:
    indices = {int(value) for value in re.findall(rf"{re.escape(tag_prefix)}(\d+)", prompt)}
    expected = set(range(1, reference_count + 1))
    missing = sorted(expected - indices)
    unexpected = sorted(indices - expected)
    if missing or unexpected:
        details = []
        if missing:
            details.append("missing " + ", ".join(f"{tag_prefix}{idx}" for idx in missing))
        if unexpected:
            details.append("unexpected " + ", ".join(f"{tag_prefix}{idx}" for idx in unexpected))
        raise ValueError("invalid reference tags: " + "; ".join(details))


def read_lore_front(ep_dir: Path) -> dict[str, object]:
    """Read simple project front matter, then apply episode overrides."""
    def parse(path: Path) -> dict[str, object]:
        if not path.exists():
            return {}
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return {}
        out: dict[str, object] = {}
        for line in text.splitlines()[1:]:
            if line.strip() == "---":
                break
            if ":" not in line or line.startswith((" ", "\t")):
                continue
            key, raw = line.split(":", 1)
            value = raw.strip().strip("'\"")
            if not value:
                continue
            if value.startswith("[") and value.endswith("]"):
                out[key.strip()] = [
                    item.strip().strip("'\"")
                    for item in value[1:-1].split(",")
                    if item.strip()
                ]
            else:
                out[key.strip()] = value
        return out

    front = parse(ep_dir.parent / "lore.md")
    front.update(parse(ep_dir / "lore.md"))
    return front
