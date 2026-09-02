"""Prompt-language detection and project-level resolution.

Creative prompt language is independent from the provider account site.  A
project may explicitly choose ``zh`` or ``en``; ``auto`` preserves the source
language and only uses the provider site when the text itself is inconclusive.
"""
from __future__ import annotations

import re
from pathlib import Path

VALID_PROMPT_LANGUAGES = {"auto", "zh", "en"}
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]+")


def normalise_prompt_language(value: str | None) -> str:
    raw = (value or "auto").strip().lower().replace("_", "-")
    aliases = {
        "auto": "auto",
        "zh": "zh",
        "zh-cn": "zh",
        "chinese": "zh",
        "中文": "zh",
        "en": "en",
        "en-us": "en",
        "english": "en",
        "英文": "en",
    }
    if raw not in aliases:
        raise ValueError(
            f"unsupported prompt_language {value!r}; choose auto, zh, or en"
        )
    return aliases[raw]


def detect_prompt_language(text: str | None) -> str | None:
    """Return the dominant language of *text*, or ``None`` when inconclusive."""
    value = text or ""
    cjk = len(_CJK_RE.findall(value))
    latin_words = len(_LATIN_WORD_RE.findall(value))
    if not cjk and not latin_words:
        return None
    # Compare Han characters with Latin words rather than Latin characters:
    # Chinese prompts commonly contain long camera/model tokens such as
    # "cinematic lighting", which should not flip an otherwise Chinese prompt.
    return "zh" if cjk >= latin_words * 2 else "en"


def resolve_prompt_language(
    *,
    explicit: str | None = None,
    text: str | None = None,
    site: str | None = None,
) -> str:
    configured = normalise_prompt_language(explicit)
    if configured != "auto":
        return configured
    detected = detect_prompt_language(text)
    if detected:
        return detected
    return "en" if (site or "").strip().lower() == "intl" else "zh"


def read_project_prompt_language(ep_dir: Path) -> str:
    """Read ``prompt_language`` from project/episode lore front-matter.

    Episode lore overrides project lore. This parser is intentionally
    dependency-free because ``render_shot.py`` has a minimal uv environment.
    """
    value = "auto"
    for lore_path in (ep_dir.parent / "lore.md", ep_dir / "lore.md"):
        if not lore_path.is_file():
            continue
        text = lore_path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        for line in text.splitlines()[1:]:
            if line.strip() == "---":
                break
            if line.startswith((" ", "\t")) or ":" not in line:
                continue
            key, raw = line.split(":", 1)
            if key.strip() == "prompt_language":
                candidate = raw.split("#", 1)[0].strip().strip("'\"")
                if candidate:
                    value = normalise_prompt_language(candidate)
    return value
