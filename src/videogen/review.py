"""Per-clip quality review via qwen3-vl-plus (DashScope multimodal).

Each rendered shot is scored on six axes:
  - logic              narrative / continuity logic
  - proportion         anatomy / scale / perspective
  - physics            gravity / collisions / momentum / cloth / fluids
  - style              matches lore.mood_anchor / visual_style / palette
  - cast_match         each visible character matches their cast portrait
  - dialog_attribution dialog is delivered by the correct character (no swap)

Score is 0-10 (the average of the six). Verdict is ACCEPT (score >= threshold)
or REJECT. Critique is a free-form Chinese string the auto-rewriter feeds back
to the prompt rewriter or the director subagent.

We use DashScope's OpenAI-compatible chat completions endpoint so the
multimodal video + reference-image input has the same shape across all
qwen-vl models — this avoids drift if Alibaba renames the native endpoint.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import SETTINGS
from .lore import Lore
from .storyboard import Scene, Shot

OPENAI_COMPAT_PATH = "/compatible-mode/v1/chat/completions"

REVIEW_AXES = (
    "logic",
    "proportion",
    "physics",
    "style",
    "cast_match",
    "dialog_attribution",
)


def _system_prompt() -> str:
    return (
        "你是一名专业 AI 视频审片师。你的任务是看完一段 AI 生成的短视频后, "
        "用客观、犀利、可执行的语言给出 0-10 分评分(支持半分), 并指出具体问题。"
        "你不写客套话, 不做总评, 只给可定位的画面问题(发生在第几秒、画面里哪部分)。"
        "评分维度严格遵守如下六项, 各自 0-10 分:\n"
        "  - logic: 镜头内动作是否符合叙事意图与剧本前后逻辑。\n"
        "  - proportion: 角色比例 / 五官 / 手脚 / 透视是否合理。\n"
        "  - physics: 重力 / 碰撞 / 流体 / 衣物 / 运动惯性是否符合现实。\n"
        "  - style: 是否贴合给定的 mood_anchor / visual_style / palette。\n"
        "  - cast_match: 视频里每个出镜角色的脸型 / 发型 / 服饰 / 体态 是否与"
        "    我额外提供的同名参考图一致。识别度有问题 / 与参考图明显是另一个人, 重扣分。\n"
        "  - dialog_attribution: 视频里说话的人是否就是台词归属的那个角色。"
        "    如果剧本规定 A 说的台词被 B 嘴型对上 / B 出声、或 A 的嘴动了但说出 B 的台词, "
        "    都视为严重错位, 记 0-3 分。无台词的镜头给 10 分。\n"
        "score = 六项的算术平均(保留 1 位小数)。"
        "结果必须是一段合法 JSON, 不要包裹 markdown 代码块, 字段如下:\n"
        '  {"score": float, '
        '"breakdown": {"logic": float, "proportion": float, "physics": float, '
        '"style": float, "cast_match": float, "dialog_attribution": float}, '
        '"critique": "...", "verdict": "ACCEPT" | "REJECT"}'
    )


def _user_prompt(
    shot: Shot,
    scene: Scene | None,
    lore: Lore | None,
    threshold: float,
    cast_entries: list[dict],
) -> str:
    lines: list[str] = []
    lines.append(f"## 镜头 ID: {shot.id}")
    lines.append(f"## 时长: {shot.duration}s")
    lines.append(f"## 类型: {shot.kind}")
    if shot.characters:
        lines.append(f"## 出场角色 (cast 中已登记): {', '.join(shot.characters)}")
    if shot.narrative_purpose:
        lines.append(f"## 叙事目的: {shot.narrative_purpose}")
    lines.append(f"## prompt (含台词归属、嘴型同步对象):\n{shot.prompt}")
    if scene is not None:
        lines.append(f"## 场景描述: {scene.description}")
    if lore is not None and lore.front:
        f = lore.front
        if f.mood_anchor:
            lines.append(f"## mood_anchor (style 维度的核心参考): {f.mood_anchor}")
        if f.visual_style:
            lines.append(f"## visual_style: {f.visual_style}")
        if f.palette:
            lines.append(f"## palette: {f.palette}")
        if f.forbidden:
            lines.append(f"## forbidden (出现即应扣分): {', '.join(f.forbidden)}")
    if cast_entries:
        lines.append("## 出场角色参考图说明 (用于 cast_match 维度)")
        for c in cast_entries:
            lines.append(f"  - 角色「{c['name']}」: 见随后传入的同名参考图。")
        lines.append(
            "  如果视频里同名角色与对应参考图的脸 / 发 / 服饰差距明显, "
            "扣 cast_match 分。如果出现 cast 之外的 named 角色, 也在 critique 里点出。"
        )
    if shot.characters and any(_seems_dialog(shot.prompt, c) for c in shot.characters):
        lines.append(
            "## 台词归属注意事项 (用于 dialog_attribution 维度)\n"
            "  请读 prompt, 找出每句台词的指定说话人, 再观察视频里实际说话/嘴动的"
            "是不是同一个人。出现错位 (A 的台词被 B 念) → dialog_attribution 重扣。"
        )
    lines.append(f"## 通过阈值: {threshold:.1f} (score >= 阈值 → ACCEPT)")
    lines.append("")
    lines.append(
        "请对照以上信息观看视频与参考图, 输出 JSON 评分。"
        "critique 必须给出可定位的具体问题(几秒, 画面哪里, 哪个角色, 错在哪里)。"
    )
    return "\n".join(lines)


_DIALOG_HINTS = ("说: ", "说：", "对.*说", "喊", "对白", "台词", "回答", "问")


def _seems_dialog(prompt: str, character: str) -> bool:
    """Cheap heuristic: does the prompt seem to attribute dialog to this character?"""
    if character not in prompt:
        return False
    # Any common Chinese dialog hint appearing in the same prompt is enough.
    return any(re.search(h, prompt) for h in _DIALOG_HINTS)


def _strip_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else text


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
def _call_qwen_vl(
    video_url: str,
    system: str,
    user: str,
    *,
    model: str,
    cast_entries: list[dict],
) -> dict:
    """Send video + per-character portrait images + the text prompt."""
    user_content: list[dict[str, Any]] = [
        {"type": "video_url", "video_url": {"url": video_url}},
    ]
    # Attach each cast portrait, prefixed with a label so the model can map
    # image → character name. Order matches the labels listed in the user text.
    for c in cast_entries:
        url = c.get("image_url")
        if not url:
            continue
        user_content.append(
            {"type": "text", "text": f"以下是角色「{c['name']}」的参考图:"}
        )
        user_content.append({"type": "image_url", "image_url": {"url": url}})
    user_content.append({"type": "text", "text": user})

    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
    }
    url = SETTINGS.base_url.rstrip("/") + OPENAI_COMPAT_PATH
    if "/api/v1" in url:
        url = url.replace("/api/v1", "")
    headers = {
        "Authorization": f"Bearer {SETTINGS.require_api_key()}",
        "Content-Type": "application/json",
        "X-DashScope-OssResourceResolve": "enable",
    }
    with httpx.Client(timeout=180.0) as c:
        r = c.post(url, json=body, headers=headers)
        r.raise_for_status()
        return r.json()


def _select_cast_entries(shot: Shot, cast_data: dict | None) -> list[dict]:
    """Return the cast entries (with image_url) for characters in this shot."""
    if not cast_data:
        return []
    by_name = {c["name"]: c for c in cast_data.get("characters", [])}
    out: list[dict] = []
    for name in shot.characters:
        c = by_name.get(name)
        if not c:
            continue
        # Only include entries that have an OSS portrait URL — qwen-vl can't
        # ingest local-only paths, and the renderer always uploads.
        if c.get("image_url"):
            out.append({"name": c["name"], "image_url": c["image_url"]})
    return out


def review_clip(
    video_url: str,
    *,
    shot: Shot,
    scene: Scene | None,
    lore: Lore | None,
    cast_data: dict | None = None,
    threshold: float | None = None,
    model: str | None = None,
) -> dict:
    """Return {score, breakdown, critique, verdict}.

    Falls back to a permissive ACCEPT (score=10, critique="review_disabled")
    only when called with explicit model="" — useful for unit tests / dry runs.
    """
    threshold = threshold if threshold is not None else SETTINGS.review_threshold
    model = model if model is not None else SETTINGS.review_model
    if not model:
        return {
            "score": 10.0,
            "breakdown": {ax: 10.0 for ax in REVIEW_AXES},
            "critique": "review_disabled",
            "verdict": "ACCEPT",
            "raw": None,
        }

    cast_entries = _select_cast_entries(shot, cast_data)
    system = _system_prompt()
    user = _user_prompt(shot, scene, lore, threshold, cast_entries)
    raw = _call_qwen_vl(
        video_url, system, user, model=model, cast_entries=cast_entries,
    )
    try:
        text = raw["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"qwen-vl response shape unexpected: {raw}") from e

    try:
        parsed = json.loads(_strip_json(text))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"qwen-vl returned non-JSON content: {text!r}") from e

    parsed = _normalize(parsed, threshold)
    parsed["raw"] = text
    return parsed


def _normalize(parsed: dict, threshold: float) -> dict:
    bd = parsed.get("breakdown") or {}
    scores: list[float] = []
    norm_bd: dict[str, float] = {}
    for ax in REVIEW_AXES:
        v = bd.get(ax, parsed.get("score", 0.0))
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 0.0
        v = max(0.0, min(10.0, v))
        norm_bd[ax] = round(v, 2)
        scores.append(v)
    score = parsed.get("score")
    if score is None:
        score = sum(scores) / max(len(scores), 1)
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = sum(scores) / max(len(scores), 1)
    score = round(max(0.0, min(10.0, score)), 2)
    critique = str(parsed.get("critique", "")).strip()
    verdict = "ACCEPT" if score >= threshold else "REJECT"
    return {
        "score": score,
        "breakdown": norm_bd,
        "critique": critique or "(no critique returned)",
        "verdict": verdict,
    }
