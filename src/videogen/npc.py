"""NPC portrait generation via Wan text-to-image.

When the storyboard references characters (e.g. 少林方丈, 武当冲虚道长) who
have dialog or are explicitly mentioned but lack a cast entry (no portrait
image), this module generates a portrait for them using the text2image API,
then saves it into the project cast directory so `cast init` can pick it up.

This solves the "character drift" problem: without a reference_image, the
video model invents a different appearance for each shot, breaking continuity.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console

from . import state, upload as up
from .config import SETTINGS
from .cast import episode_cast_dir, project_cast_dir

console = Console()

T2I_MODEL = "wan2.6-t2i"
T2I_SYNC_PATH = "/services/aigc/multimodal-generation/generation"
T2I_ASYNC_PATH = "/services/aigc/image-generation/generation"
TASK_QUERY_PATH = "/tasks"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {SETTINGS.require_api_key()}",
        "Content-Type": "application/json",
    }


def _async_headers() -> dict[str, str]:
    h = _headers()
    h["X-DashScope-Async"] = "enable"
    return h


def generate_portrait(
    name: str,
    description: str,
    *,
    project_id: str,
    episode_id: str | None = None,
    size: str = "1280*1280",
    negative_prompt: str = "低分辨率, 错误, 最差质量, 残缺, 多余的手指, 现代服装, 西装",
    mood_anchor: str = "",
) -> Path:
    """Generate a portrait for an NPC and save to a per-character cast folder.

    The portrait is written to:
      • ``projects/<id>/<episode>/cast/<name>/<name>.png`` if ``episode_id`` is
        given (recommended for episode-only NPCs).
      • ``projects/<id>/cast/<name>/<name>.png`` otherwise (shared NPC).

    The folder is created if missing — so a subsequent ``cast init`` picks
    the new character up automatically.

    Args:
        name: Character display name (e.g. '少林方丈')
        description: Detailed appearance description for t2i prompt
        project_id: Target project
        episode_id: Target episode (optional — omit for project-level NPC)
        size: Image size (default square 1280x1280 for cast portrait)
        negative_prompt: What to avoid
        mood_anchor: Project mood anchor to append for style consistency

    Returns:
        Path to the saved portrait image.
    """
    prompt = _build_portrait_prompt(name, description, mood_anchor)

    console.print(f"[cyan]generating portrait for {name}…[/]")
    image_url = _call_t2i(prompt, negative_prompt=negative_prompt, size=size)

    if episode_id:
        char_dir = episode_cast_dir(project_id, episode_id) / name
    else:
        char_dir = project_cast_dir(project_id) / name
    char_dir.mkdir(parents=True, exist_ok=True)
    out_path = char_dir / f"{name}.png"

    _download_image(image_url, out_path)
    console.print(f"[green]✓ portrait saved → {out_path}[/]")
    return out_path


def _build_portrait_prompt(name: str, description: str, mood_anchor: str) -> str:
    """Compose the t2i prompt for a character portrait."""
    parts = [
        f"人物肖像, {name}",
        description,
        "半身像, 正面面对镜头, 清晰面部特征, 高质量, 细腻光影",
    ]
    if mood_anchor:
        parts.append(mood_anchor)
    return ", ".join(parts)


def _call_t2i(
    prompt: str,
    *,
    negative_prompt: str = "",
    size: str = "1280*1280",
    n: int = 1,
) -> str:
    """Call wan2.6-t2i synchronous API, return image URL."""
    url = SETTINGS.base_url + T2I_SYNC_PATH
    body: dict[str, Any] = {
        "model": T2I_MODEL,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ]
        },
        "parameters": {
            "prompt_extend": True,
            "watermark": False,
            "n": n,
            "negative_prompt": negative_prompt,
            "size": size,
        },
    }

    with httpx.Client(timeout=120.0) as c:
        r = c.post(url, json=body, headers=_headers())
        if r.status_code == 200:
            data = r.json()
            if data.get("code"):
                raise RuntimeError(f"t2i sync failed: {data['code']} — {data.get('message')}")
            choices = data.get("output", {}).get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", [])
                for item in content:
                    if item.get("type") == "image":
                        return item["image"]
            raise RuntimeError(f"t2i returned no image: {data}")

    # Fallback: async path (for non-wan2.6 compatible endpoints)
    return _call_t2i_async(prompt, negative_prompt=negative_prompt, size=size)


def _call_t2i_async(
    prompt: str,
    *,
    negative_prompt: str = "",
    size: str = "1280*1280",
) -> str:
    """Fallback: async task submission + polling."""
    url = SETTINGS.base_url + T2I_ASYNC_PATH
    body: dict[str, Any] = {
        "model": T2I_MODEL,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ]
        },
        "parameters": {
            "prompt_extend": True,
            "watermark": False,
            "n": 1,
            "negative_prompt": negative_prompt,
            "size": size,
        },
    }

    with httpx.Client(timeout=60.0) as c:
        r = c.post(url, json=body, headers=_async_headers())
        r.raise_for_status()
        data = r.json()

    if data.get("code"):
        raise RuntimeError(f"t2i async submit failed: {data}")
    task_id = data["output"]["task_id"]
    console.print(f"[dim]  t2i task: {task_id}[/]")

    # Poll
    for _ in range(60):
        time.sleep(5)
        query_url = f"{SETTINGS.base_url}/tasks/{task_id}"
        with httpx.Client(timeout=30.0) as c:
            r = c.get(query_url, headers=_headers())
            r.raise_for_status()
            result = r.json()

        status = result.get("output", {}).get("task_status")
        if status == "SUCCEEDED":
            results = result["output"].get("results", [])
            if results and results[0].get("url"):
                return results[0]["url"]
            raise RuntimeError(f"t2i succeeded but no URL in results: {result}")
        if status in ("FAILED", "CANCELED"):
            raise RuntimeError(f"t2i task {status}: {result}")

    raise TimeoutError(f"t2i task {task_id} timed out after 5 min")


def _download_image(url: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60.0, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        out.write_bytes(r.content)


def generate_npcs_for_project(
    project_id: str,
    npcs: list[dict[str, str]],
    *,
    episode_id: str | None = None,
    mood_anchor: str = "",
) -> list[Path]:
    """Batch generate portraits for multiple NPCs.

    Args:
        project_id: Target project
        npcs: List of dicts with 'name' and 'description' keys.
              description should detail appearance: age, clothing, accessories, etc.
        episode_id: Save into the episode's cast folder when given.
        mood_anchor: From lore.md, for style consistency.

    Returns:
        List of saved portrait paths.
    """
    paths: list[Path] = []
    for npc in npcs:
        name = npc["name"]
        desc = npc["description"]
        p = generate_portrait(
            name, desc,
            project_id=project_id,
            episode_id=episode_id,
            mood_anchor=mood_anchor,
        )
        paths.append(p)
    return paths
