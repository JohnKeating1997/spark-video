"""Deterministic fingerprints for the user-approved per-shot visual contract.

This module is deliberately stdlib-only so ``scripts/gate.py`` can use it
without pulling the Pydantic runtime into the fast completeness checks.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def approval_contract(shot: dict[str, Any]) -> dict[str, Any]:
    """Return the fields whose meaning is approved with an animatic panel.

    When ``animatic_prompt`` exists it is the approved visual composition;
    literal video-prompt rewrites may then improve model compliance without
    invalidating GATE 2. If no animatic prompt exists, the render prompt is the
    only visual contract and therefore participates in the fingerprint.
    """
    animatic_prompt = shot.get("animatic_prompt")
    visual_prompt = animatic_prompt or shot.get("prompt") or ""
    return {
        "shot_id": shot.get("id"),
        "scene": shot.get("scene"),
        "duration": shot.get("duration"),
        "kind": shot.get("kind"),
        "role": shot.get("role"),
        "animatic_style": shot.get("animatic_style"),
        "visual_prompt": visual_prompt,
        "camera_path": shot.get("camera_path"),
        "end_composition": shot.get("end_composition"),
        "narrative_purpose": shot.get("narrative_purpose"),
        "narration_text": shot.get("narration_text"),
        "speech_source": shot.get("speech_source"),
        "speaker": shot.get("speaker"),
        "speech_text": shot.get("speech_text"),
        "visual_speech_mode": shot.get("visual_speech_mode"),
        "allow_generated_text": bool(shot.get("allow_generated_text", False)),
        "long_take_reason": shot.get("long_take_reason"),
        "beats": list(shot.get("beats") or []),
        "characters": list(shot.get("characters") or []),
        "props": list(shot.get("props") or []),
        "set_id": shot.get("set_id"),
        "transition_from_previous": shot.get("transition_from_previous"),
        "use_prev_last_frame_as_first": bool(
            shot.get("use_prev_last_frame_as_first", False)
        ),
    }


def contract_fingerprint(shot: dict[str, Any]) -> str:
    payload = json.dumps(
        approval_contract(shot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def storyboard_contract_fingerprint(storyboard: dict[str, Any]) -> str:
    """Fingerprint episode-level choices approved with GATE 2."""
    contract = {
        key: storyboard.get(key)
        for key in (
            "project_id", "target_duration_s", "resolution", "ratio", "mode",
            "provider", "video_model", "audio",
        )
    }
    payload = json.dumps(
        contract,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def contract_mismatches(
    storyboard: dict[str, Any],
    manifest: dict[str, Any],
) -> list[str]:
    """Return shot ids missing a current animatic-contract fingerprint."""
    current = {
        str(shot["id"]): contract_fingerprint(shot)
        for shot in storyboard.get("shots", []) or []
        if isinstance(shot, dict) and shot.get("id")
    }
    recorded: dict[str, str] = {}
    for panel in manifest.get("panels", []) or []:
        if not isinstance(panel, dict):
            continue
        shots = panel.get("shots") or []
        if len(shots) != 1 or not isinstance(shots[0], str):
            continue
        fingerprints = panel.get("contract_fingerprints")
        fingerprint = (
            fingerprints.get(shots[0])
            if isinstance(fingerprints, dict)
            else panel.get("contract_fingerprint")
        )
        if isinstance(fingerprint, str):
            recorded[shots[0]] = fingerprint
    mismatches = sorted(
        shot_id
        for shot_id, fingerprint in current.items()
        if recorded.get(shot_id) != fingerprint
    )
    if (
        manifest.get("storyboard_contract_fingerprint")
        != storyboard_contract_fingerprint(storyboard)
    ):
        mismatches.insert(0, "<storyboard>")
    return mismatches
