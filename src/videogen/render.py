"""Render shots into MP4 clips — parallel by chain-group, with per-clip review.

Architecture (Zone 2 + Zone 3 of the multi-agent pipeline):

  1. Slice storyboard.shots into **chain groups** by `use_prev_last_frame_as_first`.
     A new group starts at every shot with that flag = false.
     Within a group: sequential (each shot needs the previous shot's last_frame
     uploaded to OSS as the next first_frame).
     Across groups: parallel up to SETTINGS.max_concurrency.

  2. Per shot, run the **review loop**:
       for ver in 1..max_retry:
           render(shot, prompt=current_prompt) → clips/<id>-ver<N>.mp4
           review = qwen3-vl-plus(clip)
           if review.score >= threshold: break
           if ver < max_retry-1:  current_prompt = auto_rewrite(...)
           elif ver == max_retry-1: current_prompt = auto_rewrite(...)
           else: write needs_director_rewrite → exit signal
       winner = best score → copy to clips/<id>.mp4

  3. shots_state.json schema:
       {
         "<shot_id>": {
           "shot_id": str,
           "winner_version": int|null,
           "winner_path": str|null,
           "winner_last_frame_path": str|null,
           "winner_last_frame_url": str|null,
           "needs_director_rewrite": bool,
           "attempts": [
             {"version", "status", "task_id", "video_url",
              "clip_path", "last_frame_path", "last_frame_url",
              "prompt", "review"}
           ]
         }
       }
     Old single-attempt entries are migrated lazily on first write.
"""
from __future__ import annotations

import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console

from . import cast as cast_mod, ffmpeg as ff, lore as lore_mod, review as review_mod, rewrite as rewrite_mod, state, wan
from .config import SETTINGS
from .storyboard import Scene, Shot, Storyboard

console = Console()

# Sentinel return value: shot exhausted retries and needs human/director judgment.
NEEDS_DIRECTOR = "NEEDS_DIRECTOR_REWRITE"


# ---------- chain-group slicing ----------------------------------------------


@dataclass
class ChainGroup:
    """Consecutive shots that share a continuity chain (last_frame → first_frame)."""

    index: int
    shots: list[Shot] = field(default_factory=list)

    def label(self) -> str:
        if not self.shots:
            return f"chain#{self.index}(empty)"
        return f"chain#{self.index}({self.shots[0].id}→{self.shots[-1].id})"


def slice_chain_groups(shots: list[Shot]) -> list[ChainGroup]:
    """Split shots into ordered chain groups.

    A new group starts at every shot with use_prev_last_frame_as_first=False
    (and at the very first shot regardless of its flag — there's no previous
    frame to chain from).
    """
    groups: list[ChainGroup] = []
    current: ChainGroup | None = None
    for i, s in enumerate(shots):
        starts_new = (i == 0) or (not s.use_prev_last_frame_as_first)
        if starts_new or current is None:
            current = ChainGroup(index=len(groups))
            groups.append(current)
        current.shots.append(s)
    return groups


# ---------- shots_state schema (with backward-compat migration) --------------


def _empty_shot_record(shot_id: str) -> dict:
    return {
        "shot_id": shot_id,
        "winner_version": None,
        "winner_path": None,
        "winner_last_frame_path": None,
        "winner_last_frame_url": None,
        "needs_director_rewrite": False,
        "attempts": [],
    }


def _migrate_legacy(rec: dict) -> dict:
    """Convert the old flat single-attempt schema into the versioned shape."""
    if "attempts" in rec and isinstance(rec["attempts"], list):
        return rec
    if "status" not in rec:
        # Already empty / new shape.
        return _empty_shot_record(rec.get("shot_id", "unknown"))
    legacy_attempt = {
        "version": 1,
        "status": rec.get("status"),
        "task_id": rec.get("task_id"),
        "video_url": rec.get("video_url"),
        "clip_path": rec.get("clip_path"),
        "last_frame_path": rec.get("last_frame_path"),
        "last_frame_url": rec.get("last_frame_url"),
        "prompt": rec.get("prompt"),
        "review": None,
        "error": rec.get("error"),
    }
    succeeded = rec.get("status") == "SUCCEEDED"
    out = _empty_shot_record(rec.get("shot_id", "unknown"))
    out["attempts"] = [legacy_attempt]
    if succeeded:
        out["winner_version"] = 1
        out["winner_path"] = rec.get("clip_path")
        out["winner_last_frame_path"] = rec.get("last_frame_path")
        out["winner_last_frame_url"] = rec.get("last_frame_url")
    return out


def load_shots_state(project_id: str, episode_id: str) -> dict:
    raw = state.read_json(
        project_id, "shots_state.json", episode_id=episode_id, default={}
    ) or {}
    return {sid: _migrate_legacy(rec) for sid, rec in raw.items()}


# ---------- small utilities --------------------------------------------------


def _versioned_clip_path(edir: Path, shot_id: str, version: int) -> Path:
    return edir / "clips" / f"{shot_id}-ver{version}.mp4"


def _versioned_frame_path(edir: Path, shot_id: str, version: int) -> Path:
    return edir / "frames" / f"{shot_id}-ver{version}_last.png"


def _winner_clip_path(edir: Path, shot_id: str) -> Path:
    return edir / "clips" / f"{shot_id}.mp4"


def _winner_frame_path(edir: Path, shot_id: str) -> Path:
    return edir / "frames" / f"{shot_id}_last.png"


def _review_path(edir: Path, shot_id: str, version: int) -> Path:
    p = edir / "reviews"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{shot_id}-ver{version}.json"


def _media_for_shot(shot: Shot, cast_data: dict, prev_last_frame_url: str | None) -> tuple[str, list[dict]]:
    """Return (model, media[]) for the Wan request."""
    char_index = {c["name"]: c for c in cast_data["characters"]}
    media: list[dict] = []

    if shot.model == "wan2.7-r2v":
        for name in shot.characters:
            c = char_index.get(name)
            if not c:
                raise ValueError(f"shot {shot.id} references unknown cast '{name}'")
            entry: dict[str, Any] = {"type": "reference_image", "url": c["image_url"]}
            if c.get("audio_url"):
                entry["reference_voice"] = c["audio_url"]
            media.append(entry)
        if prev_last_frame_url and shot.use_prev_last_frame_as_first:
            media.append({"type": "first_frame", "url": prev_last_frame_url})

    elif shot.model == "wan2.7-i2v-2026-04-25":
        if not prev_last_frame_url:
            raise ValueError(
                f"i2v shot {shot.id} needs a previous last frame; "
                f"set use_prev_last_frame_as_first=true on a chained predecessor "
                f"or switch model to t2v / r2v."
            )
        media.append({"type": "first_frame", "url": prev_last_frame_url})
    return shot.model, media


def _ensure_oss_url_for(path_str: str | None) -> str | None:
    if not path_str:
        return None
    p = Path(path_str)
    if not p.exists():
        return None
    from . import upload as up
    return up.upload(str(p))


# ---------- per-attempt rendering --------------------------------------------


def _render_one_attempt(
    project_id: str,
    episode_id: str,
    shot: Shot,
    *,
    storyboard: Storyboard,
    prompt: str,
    version: int,
    prev_last_frame_url: str | None,
    cast_data: dict,
) -> dict:
    """One Wan submission → wait → download → extract last frame.

    Returns an attempt record dict (always — caller inspects .status).
    Never raises for upstream failures; it captures them in the dict.
    """
    edir = state.episode_dir(project_id, episode_id)
    clip_path = _versioned_clip_path(edir, shot.id, version)
    last_frame_path = _versioned_frame_path(edir, shot.id, version)

    model, media = _media_for_shot(shot, cast_data, prev_last_frame_url)
    input_obj: dict[str, Any] = {"prompt": prompt}
    if shot.negative_prompt:
        input_obj["negative_prompt"] = shot.negative_prompt
    if media:
        input_obj["media"] = media
    parameters: dict[str, Any] = {
        "resolution": storyboard.resolution,
        "ratio": storyboard.ratio,
        "duration": shot.duration,
        "prompt_extend": True,
        "watermark": False,
    }
    if shot.seed is not None:
        parameters["seed"] = shot.seed

    console.print(f"[bold cyan]→ submit {shot.id} ver{version}[/] model={model} dur={shot.duration}s")
    try:
        resp = wan.submit(model, input=input_obj, parameters=parameters)
    except Exception as e:  # noqa: BLE001
        return {
            "version": version, "status": "FAILED", "error": f"submit: {e}",
            "task_id": None, "video_url": None,
            "clip_path": None, "last_frame_path": None, "last_frame_url": None,
            "prompt": prompt, "review": None,
        }
    task_id = resp["output"]["task_id"]

    try:
        result = wan.wait(task_id)
    except Exception as e:  # noqa: BLE001
        return {
            "version": version, "status": "FAILED", "error": f"wait: {e}",
            "task_id": task_id, "video_url": None,
            "clip_path": None, "last_frame_path": None, "last_frame_url": None,
            "prompt": prompt, "review": None,
        }

    status = result.get("output", {}).get("task_status")
    if status != "SUCCEEDED":
        msg = result.get("output", {}).get("message") or result
        console.print(f"[red]✗ {shot.id} ver{version} {status}: {msg}[/]")
        return {
            "version": version, "status": status or "FAILED",
            "error": str(msg), "task_id": task_id, "video_url": None,
            "clip_path": None, "last_frame_path": None, "last_frame_url": None,
            "prompt": prompt, "review": None,
        }

    video_url = result["output"]["video_url"]
    ff.download(video_url, clip_path)
    ff.extract_last_frame(clip_path, last_frame_path)
    console.print(f"[green]✓ {shot.id} ver{version} → {clip_path.name}[/]")
    return {
        "version": version,
        "status": "SUCCEEDED",
        "task_id": task_id,
        "video_url": video_url,
        "clip_path": str(clip_path),
        "last_frame_path": str(last_frame_path),
        "last_frame_url": None,  # uploaded only when needed for next shot in chain
        "prompt": prompt,
        "review": None,
        "error": None,
    }


# ---------- per-shot review loop ---------------------------------------------


@dataclass
class RenderConfig:
    do_review: bool = True
    threshold: float = 7.0
    max_retry: int = 3
    do_auto_rewrite: bool = True
    review_model: str = "qwen3-vl-plus"
    rewrite_model: str = "qwen-plus"

    @classmethod
    def from_settings(cls, **overrides: Any) -> "RenderConfig":
        cfg = cls(
            do_review=True,
            threshold=SETTINGS.review_threshold,
            max_retry=SETTINGS.max_retry,
            do_auto_rewrite=True,
            review_model=SETTINGS.review_model,
            rewrite_model=SETTINGS.rewrite_model,
        )
        for k, v in overrides.items():
            if v is not None and hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg


def _set_winner(rec: dict, edir: Path, attempt: dict) -> None:
    rec["winner_version"] = attempt["version"]
    rec["winner_path"] = attempt["clip_path"]
    rec["winner_last_frame_path"] = attempt["last_frame_path"]
    rec["winner_last_frame_url"] = attempt.get("last_frame_url")
    # Maintain stable clips/<id>.mp4 + frames/<id>_last.png pointing at winner.
    if attempt["clip_path"]:
        winner_clip = _winner_clip_path(edir, rec["shot_id"])
        winner_clip.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(attempt["clip_path"], winner_clip)
    if attempt["last_frame_path"]:
        winner_frame = _winner_frame_path(edir, rec["shot_id"])
        winner_frame.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(attempt["last_frame_path"], winner_frame)


def _attempt_score(att: dict) -> float:
    rev = att.get("review") or {}
    try:
        return float(rev.get("score", -1.0))
    except (TypeError, ValueError):
        return -1.0


def _pick_best_attempt(attempts: list[dict]) -> dict | None:
    succeeded = [a for a in attempts if a.get("status") == "SUCCEEDED"]
    if not succeeded:
        return None
    return max(succeeded, key=_attempt_score)


def _persist_review(edir: Path, shot_id: str, version: int, review: dict) -> None:
    p = _review_path(edir, shot_id, version)
    p.write_text(__import__("json").dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")


def render_shot_with_review(
    project_id: str,
    episode_id: str,
    shot: Shot,
    *,
    storyboard: Storyboard,
    prev_last_frame_url: str | None,
    cast_data: dict,
    scene: Scene | None,
    lore_obj: Any | None,
    cfg: RenderConfig,
    state_lock: threading.Lock,
    reset: bool = False,
) -> dict:
    """Render `shot` with full review + auto-rewrite loop. Returns updated shot record."""
    edir = state.episode_dir(project_id, episode_id)

    # Snapshot/load record (under lock to keep concurrent shots from clobbering).
    with state_lock:
        all_state = load_shots_state(project_id, episode_id)
        rec = all_state.get(shot.id) or _empty_shot_record(shot.id)
        if reset:
            rec = _empty_shot_record(shot.id)
        rec["needs_director_rewrite"] = False

    current_prompt = shot.prompt
    last_review: dict | None = None

    for ver in range(1, cfg.max_retry + 1):
        attempt = _render_one_attempt(
            project_id, episode_id, shot,
            storyboard=storyboard, prompt=current_prompt, version=ver,
            prev_last_frame_url=prev_last_frame_url, cast_data=cast_data,
        )

        if cfg.do_review and attempt["status"] == "SUCCEEDED":
            try:
                review = review_mod.review_clip(
                    attempt["video_url"],
                    shot=shot, scene=scene, lore=lore_obj,
                    threshold=cfg.threshold, model=cfg.review_model,
                )
            except Exception as e:  # noqa: BLE001
                review = {
                    "score": 0.0,
                    "breakdown": {ax: 0.0 for ax in review_mod.REVIEW_AXES},
                    "critique": f"reviewer error: {e}",
                    "verdict": "REJECT",
                }
            attempt["review"] = review
            last_review = review
            _persist_review(edir, shot.id, ver, review)
            console.print(
                f"  [magenta]review[/] {shot.id} ver{ver}: "
                f"score={review['score']} verdict={review['verdict']}"
            )

        # Update record + persist atomically.
        with state_lock:
            all_state = load_shots_state(project_id, episode_id)
            rec = all_state.get(shot.id) or _empty_shot_record(shot.id)
            # Drop any stale attempt with the same version (can happen on --force re-runs).
            rec["attempts"] = [a for a in rec["attempts"] if a.get("version") != ver]
            rec["attempts"].append(attempt)
            all_state[shot.id] = rec
            state.write_json(project_id, "shots_state.json", all_state, episode_id=episode_id)

        # Decide outcome of this attempt.
        if attempt["status"] != "SUCCEEDED":
            # Render failure — count it but skip review/rewrite, retry with same prompt.
            if ver < cfg.max_retry:
                continue
            else:
                break

        if not cfg.do_review:
            # No review → first success wins.
            with state_lock:
                _set_winner(rec, edir, attempt)
                state.write_json(project_id, "shots_state.json", _persist_record(rec, project_id, episode_id), episode_id=episode_id)
            return rec

        review = attempt["review"]
        if review and review.get("verdict") == "ACCEPT":
            with state_lock:
                _set_winner(rec, edir, attempt)
                all_state = load_shots_state(project_id, episode_id)
                all_state[shot.id] = rec
                state.write_json(project_id, "shots_state.json", all_state, episode_id=episode_id)
            return rec

        # REJECTED + retries left → either auto-rewrite, or escalate on the last round.
        if ver < cfg.max_retry:
            if cfg.do_auto_rewrite and ver < cfg.max_retry - 1:
                # Auto rewrite for rounds 1..max_retry-2 (i.e. first N-2 retries).
                try:
                    current_prompt = rewrite_mod.auto_rewrite_prompt(
                        shot, scene=scene, lore=lore_obj, review=review,
                        current_prompt=current_prompt, retry_round=ver + 1,
                        model=cfg.rewrite_model,
                    )
                    console.print(
                        f"  [yellow]auto-rewrite[/] {shot.id} ver{ver+1} "
                        f"prompt updated ({len(current_prompt)} chars)"
                    )
                except Exception as e:  # noqa: BLE001
                    console.print(f"  [red]auto-rewrite failed[/] for {shot.id}: {e}")
            else:
                # Penultimate retry: still let auto-rewrite try once more so we
                # don't waste the last round with the same prompt.
                if cfg.do_auto_rewrite:
                    try:
                        current_prompt = rewrite_mod.auto_rewrite_prompt(
                            shot, scene=scene, lore=lore_obj, review=review,
                            current_prompt=current_prompt, retry_round=ver + 1,
                            model=cfg.rewrite_model,
                        )
                    except Exception as e:  # noqa: BLE001
                        console.print(f"  [red]auto-rewrite failed[/] for {shot.id}: {e}")
            continue
        else:
            # Out of retries — pick best attempt as a fallback winner *AND* flag
            # for director escalation. Stitch can still proceed using best-of-N.
            best = _pick_best_attempt(rec["attempts"])
            with state_lock:
                if best is not None:
                    _set_winner(rec, edir, best)
                rec["needs_director_rewrite"] = True
                all_state = load_shots_state(project_id, episode_id)
                all_state[shot.id] = rec
                state.write_json(project_id, "shots_state.json", all_state, episode_id=episode_id)
            console.print(
                f"  [red]✗ exhausted retries[/] {shot.id} → flagged for director rewrite "
                f"(best score {_attempt_score(best) if best else 'n/a'})"
            )
            return rec

    # Loop fell through without returning — render failures only.
    best = _pick_best_attempt(rec["attempts"])
    with state_lock:
        if best is not None:
            _set_winner(rec, edir, best)
            rec["needs_director_rewrite"] = True
        all_state = load_shots_state(project_id, episode_id)
        all_state[shot.id] = rec
        state.write_json(project_id, "shots_state.json", all_state, episode_id=episode_id)
    return rec


def _persist_record(rec: dict, project_id: str, episode_id: str) -> dict:
    """Single-record save helper: read-modify-write."""
    all_state = load_shots_state(project_id, episode_id)
    all_state[rec["shot_id"]] = rec
    return all_state


# ---------- chain group execution --------------------------------------------


def _run_chain_group(
    project_id: str,
    episode_id: str,
    group: ChainGroup,
    *,
    storyboard: Storyboard,
    cast_data: dict,
    scenes_index: dict[str, Scene],
    lore_obj: Any | None,
    cfg: RenderConfig,
    state_lock: threading.Lock,
    only_missing: bool,
    reset: bool,
) -> list[dict]:
    """Run one chain group sequentially. Returns ordered list of shot records."""
    out_records: list[dict] = []
    prev_last_frame_url: str | None = None

    for shot in group.shots:
        edir = state.episode_dir(project_id, episode_id)
        winner_clip = _winner_clip_path(edir, shot.id)

        # Skip if cached + winner exists + not forcing.
        if only_missing and not reset and winner_clip.exists():
            with state_lock:
                rec = load_shots_state(project_id, episode_id).get(shot.id) \
                    or _empty_shot_record(shot.id)
            if rec.get("winner_path"):
                console.print(f"[dim]· skip {shot.id} (cached, ver{rec.get('winner_version')})[/]")
                # Still need to provide a last-frame URL for any next shot in the chain.
                prev_last_frame_url = _ensure_chain_url(
                    rec, project_id, episode_id, state_lock,
                )
                out_records.append(rec)
                continue

        # Run review loop. prev_last_frame_url passed in for this shot's media.
        rec = render_shot_with_review(
            project_id, episode_id, shot,
            storyboard=storyboard,
            prev_last_frame_url=prev_last_frame_url,
            cast_data=cast_data,
            scene=scenes_index.get(shot.scene),
            lore_obj=lore_obj,
            cfg=cfg, state_lock=state_lock, reset=reset,
        )
        out_records.append(rec)

        # If the chain must continue, upload the winner's last frame to OSS.
        if rec.get("winner_path"):
            prev_last_frame_url = _ensure_chain_url(
                rec, project_id, episode_id, state_lock,
            )
        else:
            # Chain broke — subsequent shots in this group can't proceed.
            console.print(
                f"[red]chain {group.label()} broken at {shot.id}; aborting group[/]"
            )
            break
    return out_records


def _ensure_chain_url(
    rec: dict, project_id: str, episode_id: str, state_lock: threading.Lock
) -> str | None:
    if rec.get("winner_last_frame_url"):
        return rec["winner_last_frame_url"]
    url = _ensure_oss_url_for(rec.get("winner_last_frame_path"))
    if url:
        with state_lock:
            rec["winner_last_frame_url"] = url
            all_state = load_shots_state(project_id, episode_id)
            all_state[rec["shot_id"]] = rec
            state.write_json(project_id, "shots_state.json", all_state, episode_id=episode_id)
    return url


# ---------- public entry points ----------------------------------------------


def render_all(
    project_id: str,
    episode_id: str,
    storyboard: Storyboard,
    *,
    only_missing: bool = True,
    cfg: RenderConfig | None = None,
    concurrency: int | None = None,
    shot_ids: list[str] | None = None,
    reset: bool = False,
) -> dict:
    """Render the whole storyboard with chain-group parallelism + per-clip review.

    Returns the merged shots_state.
    """
    cfg = cfg or RenderConfig.from_settings()
    cast_data = cast_mod.load(project_id, episode_id)
    scenes_index = storyboard.scene_map()
    lore_obj = lore_mod.load(project_id, projects_dir=SETTINGS.projects_dir)

    # Filter by --shot if requested (single-shot retry).
    if shot_ids:
        target = set(shot_ids)
        shots = [s for s in storyboard.shots if s.id in target]
        if not shots:
            return load_shots_state(project_id, episode_id)
        # Single-shot retries become 1-shot groups regardless of chain flag,
        # since we can't rebuild upstream chain context on the fly.
        groups = [ChainGroup(index=i, shots=[s]) for i, s in enumerate(shots)]
    else:
        groups = slice_chain_groups(storyboard.shots)

    console.print(
        f"[bold]render plan:[/] {len(groups)} chain group(s), "
        f"concurrency={concurrency or SETTINGS.max_concurrency}"
    )
    for g in groups:
        console.print(f"  · {g.label()} ({len(g.shots)} shots)")

    state_lock = threading.Lock()
    workers = max(1, concurrency or SETTINGS.max_concurrency)
    futures = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for g in groups:
            futures[ex.submit(
                _run_chain_group,
                project_id, episode_id, g,
                storyboard=storyboard, cast_data=cast_data,
                scenes_index=scenes_index, lore_obj=lore_obj,
                cfg=cfg, state_lock=state_lock,
                only_missing=only_missing, reset=reset,
            )] = g
        for fut in as_completed(futures):
            g = futures[fut]
            try:
                fut.result()
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]chain {g.label()} crashed:[/] {e}")

    final = load_shots_state(project_id, episode_id)

    # Surface director-escalation list for the producer.
    needs = [
        sid for sid, rec in final.items()
        if rec.get("needs_director_rewrite")
        and (not shot_ids or sid in set(shot_ids))
    ]
    if needs:
        edir = state.episode_dir(project_id, episode_id)
        payload = {
            "shots": needs,
            "details": [
                {
                    "shot_id": sid,
                    "best_version": final[sid].get("winner_version"),
                    "best_score": _attempt_score(_pick_best_attempt(final[sid]["attempts"]) or {}),
                    "attempts": final[sid]["attempts"],
                }
                for sid in needs
            ],
        }
        out = edir / "needs_director_rewrite.json"
        out.write_text(
            __import__("json").dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        console.print(
            f"[red]✗ {len(needs)} shot(s) need director rewrite — see {out.name}[/]"
        )

    return final
