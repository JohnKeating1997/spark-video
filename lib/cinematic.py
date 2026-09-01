"""Deterministic duration-to-complexity budgets for cinematic shots."""
from __future__ import annotations

from typing import TypedDict


class CinematicBudget(TypedDict):
    tier: str
    label: str
    prompt_guidance: str
    prompt_guidance_zh: str


def cinematic_budget(duration: int) -> CinematicBudget:
    """Return the shot-complexity ceiling implied by picture duration."""
    if duration <= 5:
        return {
            "tier": "micro",
            "label": "micro shot · 2-5s",
            "prompt_guidance": (
                "Use one primary visible action, one simple camera move, and "
                "one immediately readable ending composition. The action may "
                "unfold through a few causally linked micro-phases, but do not "
                "add a second dramatic event, location change, or emotional turn."
            ),
            "prompt_guidance_zh": (
                "只安排一个主要可见动作、一次简单摄影机运动和一个立即可读的结束构图；"
                "该动作可以分成少量前后因果相连的微阶段，但不要增加第二个戏剧事件、"
                "地点变化或情绪转折。"
            ),
        }
    if duration <= 10:
        return {
            "tier": "core",
            "label": "core shot · 6-10s",
            "prompt_guidance": (
                "This is the default range; prefer 6-8 seconds when the action "
                "reads cleanly there. Use one complete action or compact causal "
                "progression, one camera path, and one landing composition."
            ),
            "prompt_guidance_zh": (
                "这是默认区间；动作能在6到8秒清楚完成时优先采用6到8秒。安排一个完整动作"
                "或紧凑的因果进展、一条摄影机路径和一个明确落点。"
            ),
        }
    if duration <= 15:
        return {
            "tier": "extended",
            "label": "extended shot · 11-15s",
            "prompt_guidance": (
                "Use this range only when speech, performance, or camera travel "
                "cannot land cleanly in 10 seconds. Keep one dramatic intention "
                "and split the shot if it contains an independent second event."
            ),
            "prompt_guidance_zh": (
                "仅在对白、表演或摄影机运动无法于10秒内自然完成时使用；保持单一戏剧意图，"
                "若出现可独立成立的第二事件则拆镜。"
            ),
        }
    return {
        "tier": "exceptional",
        "label": "exceptional long take · 16-30s",
        "prompt_guidance": (
            "Use only for an indivisible continuous event, deliberately sustained "
            "performance, or motivated long take. Follow the declared timeline; "
            "its number of phases is chosen by the content, never by duration."
        ),
        "prompt_guidance_zh": (
            "仅用于不可拆分的连续事件、需要持续展开的表演或有明确动机的长镜头；按声明的"
            "时间线执行，阶段数量由内容决定，不由时长决定。"
        ),
    }
