"""Auto prompt rewriter for failed shots — used in the first N-1 retries.

Given the original Wan prompt, the review report, and the project's lore /
scene context, this module asks a text LLM (default qwen3.6-plus) to
emit a revised prompt that fixes the issues called out in the critique
without losing the original narrative intent.

Only the first N-1 retries flow through here. The final retry escalates
to a director subagent (handled by the producer slash command), so this
module never has to be a perfect director — it just has to keep the
shot in the running.
"""
from __future__ import annotations

import re
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import SETTINGS
from .lore import Lore
from .storyboard import Scene, Shot

OPENAI_COMPAT_PATH = "/compatible-mode/v1/chat/completions"

PROMPT_HARD_CAP = 220  # Wan prompts > ~200 char start to drift; leave a small margin.


def _system_prompt() -> str:
    return (
        "你是一名 AI 视频生成 prompt 工程师, 擅长山音风格(动作具体、可拍、"
        "无心理描写、无括号暗示、无书面化比喻)。用户会给你: 原 Wan 2.7 prompt、"
        "审片师的具体批评、scene 描述、mood_anchor。你的任务是: 在保留原镜头叙事意图、"
        "角色、景别、运镜、台词的前提下, 修复批评指出的问题。\n\n"
        "硬性要求:\n"
        f"  1. 输出仅一段中文 prompt, 不超过 {PROMPT_HARD_CAP} 字, 无 markdown, 无解释.\n"
        "  2. mood_anchor 原文必须出现在 prompt 末尾.\n"
        "  3. 保留原 prompt 中出现的台词原话, 不允许改写台词.\n"
        "  4. 保留 '图1/图2/视频1' 等引用语法.\n"
        "  5. 不得出现 '展现冲突 / 推进剧情' 等空话; 写具体动作 / 表情 / 物体.\n"
        "  6. 不要出现心理描写或括号暗示."
    )


def _user_prompt(
    shot: Shot,
    scene: Scene | None,
    lore: Lore | None,
    review: dict,
    current_prompt: str,
    retry_round: int,
) -> str:
    lines: list[str] = []
    lines.append(f"# 第 {retry_round} 次重写 · 镜头 {shot.id}")
    if shot.narrative_purpose:
        lines.append(f"## 叙事目的: {shot.narrative_purpose}")
    if scene is not None:
        lines.append(f"## 场景描述: {scene.description}")
    if lore is not None and lore.front:
        f = lore.front
        if f.mood_anchor:
            lines.append(f"## mood_anchor (必须原文出现在末尾): {f.mood_anchor}")
        if f.visual_style:
            lines.append(f"## visual_style: {f.visual_style}")
        if f.palette:
            lines.append(f"## palette: {f.palette}")
        if f.forbidden:
            lines.append(f"## forbidden: {', '.join(f.forbidden)}")
    lines.append("")
    lines.append(f"## 原 prompt:\n{current_prompt}")
    lines.append("")
    lines.append(f"## 审片师评分: {review.get('score')}")
    bd = review.get("breakdown", {})
    if bd:
        lines.append(
            "## 各维度: " + ", ".join(f"{k}={v}" for k, v in bd.items())
        )
    lines.append(f"## 审片师批评:\n{review.get('critique', '')}")
    lines.append("")
    lines.append("请输出修复后的新 prompt。仅输出 prompt 本身, 不要任何解释或前后缀。")
    return "\n".join(lines)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
def _call_qwen_text(system: str, user: str, *, model: str) -> str:
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.4,
    }
    url = SETTINGS.base_url.rstrip("/") + OPENAI_COMPAT_PATH
    if "/api/v1" in url:
        url = url.replace("/api/v1", "")
    headers = {
        "Authorization": f"Bearer {SETTINGS.require_api_key()}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=60.0) as c:
        r = c.post(url, json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
    return data["choices"][0]["message"]["content"]


def _sanitize(text: str, mood_anchor: str | None) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    text = text.strip().strip("\"'`")
    text = text.replace("\n", " ").replace("  ", " ")
    if mood_anchor and mood_anchor not in text:
        text = f"{text}, {mood_anchor}"
    if len(text) > PROMPT_HARD_CAP:
        text = text[: PROMPT_HARD_CAP - 1] + "…"
    return text


def auto_rewrite_prompt(
    shot: Shot,
    *,
    scene: Scene | None,
    lore: Lore | None,
    review: dict,
    current_prompt: str | None = None,
    retry_round: int = 1,
    model: str | None = None,
) -> str:
    """Return a revised Wan prompt. mood_anchor is enforced at the end."""
    current_prompt = current_prompt or shot.prompt
    model = model if model is not None else SETTINGS.rewrite_model
    mood = (lore.front.mood_anchor if lore and lore.front else None)

    if not model:
        # Caller asked to disable auto-rewrite; just nudge mood anchor + keep going.
        return _sanitize(current_prompt, mood)

    system = _system_prompt()
    user = _user_prompt(shot, scene, lore, review, current_prompt, retry_round)
    raw = _call_qwen_text(system, user, model=model)
    return _sanitize(raw, mood)
