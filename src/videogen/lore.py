"""Lore — per-project story background / world bible.

Sits at ``projects/<id>/lore.md``. Like soul cards but project-scoped:
*soul* answers "who is this character", *lore* answers "what world are they in".

The director Skill reads lore BEFORE writing the script, then carries
``mood_anchor`` (a single style sentence) through every shot prompt for
visual cohesion.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .soul import _split_frontmatter  # reuse the same parser

LORE_FILENAME = "lore.md"


class LoreFront(BaseModel):
    """Validated YAML front-matter for a lore card."""

    model_config = ConfigDict(extra="allow")

    # identity
    title: str | None = None
    genre: list[str] = Field(default_factory=list)
    era: str | None = None
    location: str | None = None

    # visual / camera direction
    visual_style: str | None = None
    camera_language: str | None = None
    palette: list[str] = Field(default_factory=list)

    # The single style sentence the director Skill should append to EVERY
    # shot prompt for cohesion. Keep it short (<60 chars).
    mood_anchor: str | None = None

    # World rules — fed into negative_prompt-ish guidance and content checks.
    forbidden: list[str] = Field(default_factory=list)
    allowed: list[str] = Field(default_factory=list)

    # Optional defaults that storyboard authors can pick up.
    duration_target_s: int | None = None
    default_shot_duration: int | None = None
    default_resolution: str | None = None
    default_ratio: str | None = None


@dataclass
class Lore:
    path: str
    front: LoreFront
    body: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "front": self.front.model_dump(exclude_none=True),
            "body": self.body,
        }


def parse(path: str | Path) -> Lore:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    front_raw, body = _split_frontmatter(text)
    if front_raw:
        try:
            data = yaml.safe_load(front_raw) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"{p}: invalid YAML front-matter: {e}") from e
        if not isinstance(data, dict):
            raise ValueError(f"{p}: front-matter must be a mapping, got {type(data).__name__}")
        front = LoreFront.model_validate(data)
    else:
        front = LoreFront()
    return Lore(path=str(p.resolve()), front=front, body=body.strip())


def load(project_id: str, *, projects_dir: Path) -> Lore | None:
    p = projects_dir / project_id / LORE_FILENAME
    if not p.exists():
        return None
    return parse(p)


def render_for_prompt(lore: Lore) -> str:
    """Return a compact text the director Skill can paste into context."""
    f = lore.front
    parts: list[str] = []

    head_bits: list[str] = []
    if f.title: head_bits.append(f.title)
    if f.genre: head_bits.append("/".join(f.genre))
    if f.era: head_bits.append(f.era)
    if f.location: head_bits.append(f.location)
    if head_bits:
        parts.append(f"# 世界观: {' · '.join(head_bits)}")

    if f.mood_anchor:
        parts.append(f"- 风格锚词 (每段 prompt 末尾必带): \"{f.mood_anchor}\"")
    if f.visual_style:
        parts.append(f"- 视觉风格: {f.visual_style}")
    if f.camera_language:
        parts.append(f"- 镜头语言: {f.camera_language}")
    if f.palette:
        parts.append(f"- 色板: {', '.join(f.palette)}")
    if f.forbidden:
        parts.append(f"- 严禁出现: " + "; ".join(f.forbidden))
    if f.allowed:
        parts.append(f"- 明确允许: " + "; ".join(f.allowed))

    defaults: list[str] = []
    if f.duration_target_s: defaults.append(f"目标时长 {f.duration_target_s}s")
    if f.default_shot_duration: defaults.append(f"单段默认 {f.default_shot_duration}s")
    if f.default_resolution: defaults.append(f"分辨率 {f.default_resolution}")
    if f.default_ratio: defaults.append(f"宽高比 {f.default_ratio}")
    if defaults:
        parts.append(f"- 默认参数: {', '.join(defaults)}")

    if lore.body:
        parts.append("")
        parts.append("## 设定正文 (供 Skill 阅读)")
        parts.append(lore.body)

    return "\n".join(parts)


LORE_TEMPLATE = """\
---
# Story bible for {title}. Fill what you know; leave the rest blank.
# The director Skill reads this BEFORE writing the script, and carries
# mood_anchor through every shot prompt for visual cohesion.

title: {title}
genre: []          # e.g. [武侠喜剧, 情景喜剧]  /  [科幻, 悬疑]
era:               # 时空背景, e.g. 明朝架空 / 2049 近未来 / 维多利亚时代蒸汽朋克
location:          # 主要发生地, e.g. 七侠镇 · 同福客栈

# --- visual / camera direction ---
visual_style:      # 一句话描述, e.g. 暖色调, 喜剧光线, 略夸张的肢体语言
camera_language:   # e.g. 中近景为主, 偶尔大特写抓表情, 摇镜代替剪辑
palette: []        # color names or hex, e.g. [warm-amber, faded-red, ink-black]

# --- mood_anchor: single sentence appended to EVERY shot prompt ---
# Keep it short, concrete, and constant across the whole project.
# Example: "明朝架空, 喜剧光线, 暖色调, 略夸张的肢体语言"
mood_anchor:

# --- world rules ---
forbidden: []      # e.g. [真实历史人物姓名, IP 直接同名, 血腥镜头]
allowed: []        # e.g. [夸张武打, 第四面墙吐槽]

# --- defaults the storyboard can pick up ---
duration_target_s: 180
default_shot_duration: 8
default_resolution: 720P
default_ratio: "16:9"
---

# 世界观

(几句话讲清这是个什么世界、什么调性、为什么有趣。LLM 写剧本前会先读这段。)

## 视觉风格参考

- 灯光:
- 服饰:
- 道具/场景质感:

## 镜头语言原则

- 喜剧/紧张/惊悚的节奏处理:
- 群戏 vs 双人戏的镜头偏好:
- 转场习惯:

## 写作禁区与口味

- 严禁:
- 我喜欢:
"""
