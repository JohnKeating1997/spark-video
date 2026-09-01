"""Prompt safety — strip phrases that trigger Wan content moderation (9007).

Wan's content moderation scans both the prompt and negative_prompt for
blocked keywords. Phrases like "no explicit content" or "no gore" in a
negative_prompt trigger 9007 errors even though they are negation
instructions, because the moderation filter matches on the keyword itself
("explicit", "gore") regardless of context.

This module provides a lightweight, stdlib-only filter that strips
known trigger phrases before submission.
"""
from __future__ import annotations

# Phrases that trigger Wan 9007 content moderation even in negative_prompt
# context. Each is a full phrase (case-insensitive) that will be removed
# from the text. Add new entries here as they are discovered.
_MODERATION_TRIGGER_PHRASES: list[str] = [
    "no explicit content",
    "no realistic human faces",
    "no gore",
    "no violence",
    "no nudity",
    "no sexual content",
    "no drugs",
    "no weapons",
]

# Individual words that are risky even as standalone tokens. These are
# only stripped when they appear as part of a "no <word>" pattern in
# negative_prompt context, to avoid false positives in the main prompt.
_RISKY_WORDS_IN_NEGATION: list[str] = [
    "explicit",
    "gore",
    "nudity",
    "sexual",
]


def strip_unsafe_phrases(text: str) -> tuple[str, list[str]]:
    """Remove moderation-trigger phrases from *text*.

    Treats the text as a comma-separated list and filters out any
    segment that matches a trigger phrase (case-insensitive).

    Returns (cleaned_text, removed_phrases).

    >>> strip_unsafe_phrases("no text overlay, no gore")
    ('no text overlay', ['no gore'])
    >>> strip_unsafe_phrases("no text overlay, no gore, no realistic "
    ...                      "human faces, clean background")
    ('no text overlay, clean background', ['no gore', 'no realistic human faces'])
    >>> strip_unsafe_phrases("clean prompt")
    ('clean prompt', [])
    """
    if not text:
        return text, []
    parts = [p.strip() for p in text.split(",")]
    removed: list[str] = []
    kept: list[str] = []
    for part in parts:
        matched = False
        for phrase in _MODERATION_TRIGGER_PHRASES:
            if part.lower() == phrase.lower():
                removed.append(part)
                matched = True
                break
        if not matched:
            kept.append(part)
    cleaned = ", ".join(kept)
    return cleaned, removed
