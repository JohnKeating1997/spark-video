# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""wan-cli provider for spark-video.

Maps every provider-agnostic ``t2v`` / ``i2v`` / ``r2v`` shot kind onto Wan
3.0's unified ``wan omni2video`` path. First/last-frame inputs remain Omni
image references whose opening/ending roles are stated in the prompt. Set
``VIDEOGEN_WAN_VIDEO_MODEL`` or the per-run
``SPARK_VIDEO_WAN_VIDEO_MODEL`` override to ``wan2.7`` to route through the
matching legacy video commands. The CLI owns authentication, task polling,
and result download. This adapter explicitly uploads local images first, then
passes their returned URLs to the video command; it also classifies
references, builds the command, and copies the downloaded video to
spark-video's deterministic clip path.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from lib.cli import active_wan_site, wan_cmd, wan_media_tag
from lib.model_log import log_call, reset_context, set_context


DEFAULT_MODEL = "wan3.0"
MODEL_DURATION_LIMITS = {
    "wan3.0": (2, 30),
    "wan2.7": (2, 15),
}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_VIDEO_SUFFIXES = {".mp4", ".mov"}
_AUDIO_SUFFIXES = {".mp3", ".wav"}
_REMOTE_MEDIA_PREFIXES = ("http://", "https://", "asset://", "data:")
_TRANSIENT_ERROR_PATTERNS = (
    "httpcode\": 429",
    "httpcode: 429",
    "too many requests",
    "rate limit",
    "rate_limit",
    "访问过于火爆",
    "upstream connection",
    "upstream connect",
    "connection reset",
    "econnreset",
    "socket hang up",
    "network request failed",
    "fetch failed",
    "502 bad gateway",
    "503 service unavailable",
    "504 gateway",
    "timed out",
)


def _suffix(value: str) -> str:
    """Return a lowercase suffix for local paths and URL-like references."""
    if value.startswith("data:image/"):
        return ".png"
    if value.startswith("data:video/"):
        return ".mp4"
    if value.startswith("data:audio/"):
        return ".mp3"
    return Path(value.split("?", 1)[0]).suffix.lower()


def _append_media(
    value: str,
    *,
    images: list[str],
    videos: list[str],
    audios: list[str],
) -> None:
    suffix = _suffix(value)
    if suffix in _IMAGE_SUFFIXES:
        images.append(value)
    elif suffix in _VIDEO_SUFFIXES:
        videos.append(value)
    elif suffix in _AUDIO_SUFFIXES:
        audios.append(value)
    else:
        raise ValueError(
            f"wan-cli cannot classify reference media {value!r}; "
            "use a supported image, video, or audio file extension"
        )


def _json_from_stdout(stdout: str) -> dict[str, Any]:
    """Parse JSON even when a CLI/runtime prints harmless prefix lines."""
    text = stdout.strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {"value": value}
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise RuntimeError(f"wan returned non-JSON output: {text[-1000:]}")


def _saved_paths(payload: dict[str, Any]) -> list[Path]:
    """Return saved outputs with watermark-free resources first."""
    watermark_order = {
        "without": 0,
        "regulatory": 1,
        "unknown": 2,
        "with": 3,
    }
    ranked: list[tuple[int, int, Path]] = []
    for index, item in enumerate(payload.get("savedFiles") or []):
        raw = item.get("path") if isinstance(item, dict) else item
        if isinstance(raw, str) and raw.strip():
            watermark = (
                str(item.get("watermark") or "unknown").lower()
                if isinstance(item, dict)
                else "unknown"
            )
            ranked.append((
                watermark_order.get(watermark, watermark_order["unknown"]),
                index,
                Path(raw).expanduser(),
            ))
    return [path for _, _, path in sorted(ranked)]


def _is_transient_failure(output: str) -> bool:
    text = output.lower()
    return any(pattern in text for pattern in _TRANSIENT_ERROR_PATTERNS)


def _concise_failure(output: str) -> str:
    """Keep the useful error code/message instead of a huge upload payload."""
    code = re.search(r'["\']errorCode["\']\s*:\s*["\']([^"\']+)', output)
    message = re.search(r'["\']errorMsg["\']\s*:\s*["\']([^"\']+)', output)
    if code or message:
        parts = []
        if code:
            parts.append(f"code={code.group(1)}")
        if message:
            parts.append(message.group(1))
        return ": ".join(parts)
    return output.strip()[-2000:]


def _run(cmd: list[str], *, timeout: int) -> dict[str, Any]:
    max_attempts = max(
        1, int(os.environ.get("VIDEOGEN_WAN_CLI_MAX_ATTEMPTS", "3"))
    )
    for attempt in range(1, max_attempts + 1):
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 30,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "wan CLI is not installed. Install @wan-ai/cli, then run "
                "`wan auth login --output json`."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"wan timed out after {timeout + 30}s") from exc

        if proc.returncode == 0:
            try:
                return _json_from_stdout(proc.stdout)
            except RuntimeError:
                if attempt < max_attempts and _is_transient_failure(proc.stdout):
                    backoff = 2 ** (attempt - 1)
                    print(
                        f"wan transient non-JSON response "
                        f"(attempt {attempt}/{max_attempts}); retrying in "
                        f"{backoff}s: {_concise_failure(proc.stdout)}",
                        file=sys.stderr,
                    )
                    time.sleep(backoff)
                    continue
                raise

        combined = "\n".join(part for part in (proc.stderr, proc.stdout) if part)
        if attempt < max_attempts and _is_transient_failure(combined):
            backoff = 2 ** (attempt - 1)
            print(
                f"wan transient error (attempt {attempt}/{max_attempts}); "
                f"retrying in {backoff}s: {_concise_failure(combined)}",
                file=sys.stderr,
            )
            time.sleep(backoff)
            continue
        raise RuntimeError(
            f"wan exited {proc.returncode}: {_concise_failure(combined)}"
        )
    raise AssertionError("unreachable")


def _prepare_local_files(
    values: list[str], work_dir: Path, *, prefix: str
) -> list[str]:
    """Copy local media unchanged to comma-free paths for wan-cli lists."""
    work_dir.mkdir(parents=True, exist_ok=True)
    prepared: list[str] = []
    for index, value in enumerate(values, 1):
        if value.startswith(_REMOTE_MEDIA_PREFIXES):
            prepared.append(value)
            continue
        source = Path(value).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"reference media not found: {source}")
        target = work_dir / f"{prefix}-{index:02d}{source.suffix.lower()}"
        shutil.copy2(source, target)
        prepared.append(str(target))
    return prepared


def _full_local_audio_ranges(values: list[str]) -> list[str] | None:
    """Return full-file Omni crop ranges for local audio references.

    Wan's Omni backend may otherwise infer the output-video duration as the
    audio crop end, which fails whenever a voice reference is shorter than
    the requested clip.  Remote assets keep the CLI's existing default
    behavior because their duration is not available locally.
    """
    if not values or any(value.startswith(_REMOTE_MEDIA_PREFIXES) for value in values):
        return None
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError(
            "ffprobe is required to determine full audio reference ranges"
        )
    end_ms_values: list[int] = []
    for value in values:
        proc = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                value,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"could not determine audio duration for {value}: "
                f"{proc.stderr.strip()}"
            )
        try:
            end_ms = int(float(proc.stdout.strip()) * 1000)
        except ValueError as exc:
            raise RuntimeError(
                f"ffprobe returned an invalid duration for {value}: "
                f"{proc.stdout.strip()!r}"
            ) from exc
        if not 1000 <= end_ms <= 15000:
            raise ValueError(
                f"Wan Omni audio reference must be 1-15 seconds; "
                f"{value} is {end_ms / 1000:.3f}s"
            )
        end_ms_values.append(end_ms)
    if sum(end_ms_values) > 15000:
        raise ValueError(
            "Wan Omni audio reference ranges total more than 15 seconds; "
            "select shorter source segments explicitly"
        )

    def format_seconds(milliseconds: int) -> str:
        return f"{milliseconds / 1000:.3f}".rstrip("0").rstrip(".")

    return [f"0:{format_seconds(end_ms)}" for end_ms in end_ms_values]


def _full_local_video_ranges(values: list[str]) -> tuple[list[str], float] | None:
    """Return explicit full ranges and their total for local Omni video refs."""
    if not values or any(value.startswith(_REMOTE_MEDIA_PREFIXES) for value in values):
        return None
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError(
            "ffprobe is required to determine full video reference ranges"
        )
    durations: list[float] = []
    for value in values:
        proc = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                value,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"could not determine video duration for {value}: "
                f"{proc.stderr.strip()}"
            )
        try:
            seconds = float(proc.stdout.strip())
        except ValueError as exc:
            raise RuntimeError(
                f"ffprobe returned an invalid duration for {value}: "
                f"{proc.stdout.strip()!r}"
            ) from exc
        if not 1 <= seconds <= 15:
            raise ValueError(
                f"Wan Omni video reference must be 1-15 seconds; "
                f"{value} is {seconds:.3f}s. Select an explicit source segment."
            )
        durations.append(seconds)
    total = sum(durations)
    if total > 15:
        raise ValueError(
            "Wan Omni video reference ranges total more than 15 seconds; "
            "select shorter source segments explicitly"
        )

    def format_seconds(seconds: float) -> str:
        return f"{seconds:.3f}".rstrip("0").rstrip(".")

    return [f"0:{format_seconds(seconds)}" for seconds in durations], total


def _upload_task_type(*, model: str, kind: str) -> str:
    """Return the wan upload namespace used by the eventual video command."""
    if model == "wan3.0":
        return "omni_video_generate"
    if kind == "r2v":
        return "cast_to_video"
    return "image_to_video"


def _upload_local_images(
    values: list[str],
    *,
    repo_root: Path,
    model: str,
    kind: str,
    timeout: int,
    cache: dict[str, str] | None = None,
) -> list[str]:
    """Upload local images explicitly and replace them with returned URLs."""
    uploaded = cache if cache is not None else {}
    resolved: list[str] = []
    task_type = _upload_task_type(model=model, kind=kind)
    for value in values:
        if value.startswith(_REMOTE_MEDIA_PREFIXES):
            resolved.append(value)
            continue

        source = Path(value).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"reference image not found: {source}")
        cache_key = str(source)
        if cache_key in uploaded:
            resolved.append(uploaded[cache_key])
            continue

        cmd = wan_cmd(repo_root) + [
            "upload", str(source),
            "--task-type", task_type,
            "--asset-type", "image",
            "--model", model,
            "--url-type", "cdn_link",
            "--timeout", str(timeout),
            "--output", "json",
        ]
        upload_started = time.monotonic()
        request = {
            "file": str(source),
            "task_type": task_type,
            "asset_type": "image",
        }
        version_raw = os.environ.get("SPARK_VIDEO_ATTEMPT", "")
        token = set_context(
            project_id=os.environ.get("SPARK_VIDEO_PROJECT"),
            episode_id=os.environ.get("SPARK_VIDEO_EPISODE"),
            shot_id=os.environ.get("SPARK_VIDEO_SHOT"),
            version=int(version_raw) if version_raw.isdigit() else None,
        )
        try:
            payload = _run(cmd, timeout=timeout)
            url = str(payload.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                raise RuntimeError(
                    "wan CDN upload succeeded but returned no usable HTTP URL: "
                    f"{payload}"
                )
            log_call(
                kind="media_upload",
                provider="wan-cli",
                model=model,
                endpoint="wan CLI upload",
                request=request,
                response=payload,
                duration_ms=(time.monotonic() - upload_started) * 1000,
            )
        except Exception as exc:
            log_call(
                kind="media_upload",
                provider="wan-cli",
                model=model,
                endpoint="wan CLI upload",
                request=request,
                duration_ms=(time.monotonic() - upload_started) * 1000,
                error=str(exc),
            )
            raise
        finally:
            reset_context(token)
        uploaded[cache_key] = url
        resolved.append(url)
    return resolved


def _active_wan_site(repo_root: Path) -> str:
    """Read the effective site; unknown config defaults to international."""
    return active_wan_site(repo_root)


def _with_media_tags(
    prompt: str,
    *,
    site: str,
    image_count: int,
    video_count: int,
    audio_count: int,
) -> str:
    """Ensure Omni promptMeta references every uploaded asset in site syntax."""
    names = (
        {"image": "图片", "video": "视频", "audio": "音频"}
        if site == "cn"
        else {"image": "Image", "video": "Video", "audio": "Audio"}
    )
    tags = [f"@{names['image']}{index}" for index in range(1, image_count + 1)]
    tags.extend(f"@{names['video']}{index}" for index in range(1, video_count + 1))
    tags.extend(f"@{names['audio']}{index}" for index in range(1, audio_count + 1))
    missing = [tag for tag in tags if tag not in prompt]
    if not missing:
        return prompt
    label = "参考素材" if site == "cn" else "Reference assets"
    separator = "、" if site == "cn" else ", "
    punctuation = "。" if site == "cn" else "."
    return f"{label}: {separator.join(missing)}{punctuation}\n\n{prompt.rstrip()}"


def _video_model() -> str:
    raw = os.environ.get(
        "SPARK_VIDEO_WAN_VIDEO_MODEL",
        os.environ.get("VIDEOGEN_WAN_VIDEO_MODEL", DEFAULT_MODEL),
    ).strip().lower()
    aliases = {
        "2.7": "wan2.7",
        "2_7": "wan2.7",
        "wan2.7": "wan2.7",
        "wan2_7": "wan2.7",
        "3.0": "wan3.0",
        "3_0": "wan3.0",
        "wan3.0": "wan3.0",
        "wan3_0": "wan3.0",
    }
    try:
        return aliases[raw]
    except KeyError as exc:
        raise ValueError(
            "unsupported Wan video model "
            f"{raw!r}; choose wan2.7 or wan3.0"
        ) from exc


def _build_wan_command(
    repo_root: Path,
    *,
    model: str,
    kind: str,
    prompt: str,
    images: list[str],
    videos: list[str],
    audios: list[str],
    first_frame: str | None,
    duration: int,
    resolution: str,
    ratio: str,
    temp_dir: str,
    timeout: int,
    audio_output: bool = True,
    last_frame: str | None = None,
) -> tuple[list[str], str]:
    """Build a model-specific wan-cli command and return its effective prompt."""
    command = wan_cmd(repo_root)
    if model == "wan3.0":
        site = _active_wan_site(repo_root)
        omni_images = list(images)
        frame_guidance: list[str] = []
        if first_frame:
            if first_frame not in omni_images:
                omni_images.append(first_frame)
            tag = wan_media_tag("image", omni_images.index(first_frame) + 1, site=site)
            frame_guidance.append(
                (
                    f"{tag} 是目标开场构图。以其中的人物位置、姿态、机位和空间状态开场，"
                    "随后平滑延续指定动作。"
                )
                if site == "cn"
                else (
                    f"{tag} is the target opening-frame composition. Begin with "
                    "its subject placement, pose, camera angle, and spatial "
                    "state, then continue the requested action smoothly."
                )
            )
        if last_frame:
            if last_frame not in omni_images:
                omni_images.append(last_frame)
            tag = wan_media_tag("image", omni_images.index(last_frame) + 1, site=site)
            frame_guidance.append(
                (
                    f"{tag} 是目标结束构图。让人物位置、姿态、机位和空间状态在最后时刻"
                    "自然收敛到该构图，不要突然跳变。"
                )
                if site == "cn"
                else (
                    f"{tag} is the target ending-frame composition. Converge on "
                    "its subject placement, pose, camera angle, and spatial "
                    "state by the final moment without an abrupt jump."
                )
            )
        if frame_guidance:
            prompt = (
                f"{prompt.rstrip()}\n\n"
                + ("首尾帧引导：\n- " if site == "cn" else "Frame guidance:\n- ")
                + "\n- ".join(frame_guidance)
            )
        prompt = _with_media_tags(
            prompt,
            site=site,
            image_count=len(omni_images),
            video_count=len(videos),
            audio_count=len(audios),
        )
        command += ["omni2video", "--model", model, "--prompt", prompt]
        if omni_images:
            command += ["--images", ",".join(omni_images)]
        if videos:
            command += ["--videos", ",".join(videos)]
            video_range_data = _full_local_video_ranges(videos)
            if video_range_data:
                video_ranges, selected_video_s = video_range_data
                maximum_output_s = 30 - selected_video_s
                if duration > maximum_output_s:
                    raise ValueError(
                        "Wan Omni explicit duration cannot exceed "
                        f"30 - selected video seconds ({maximum_output_s:.3f}s); "
                        f"got {duration}s. Shorten the shot or select a shorter "
                        "reference-video segment."
                    )
                command += ["--video-ranges", ",".join(video_ranges)]
        if audios:
            command += ["--audios", ",".join(audios)]
            audio_ranges = _full_local_audio_ranges(audios)
            if audio_ranges:
                command += ["--audio-ranges", ",".join(audio_ranges)]
        command += ["--ratio", ratio]
        command += [
            "--smart-duration=false",
            f"--audio-output={'true' if audio_output else 'false'}",
        ]
    elif kind == "t2v" and not first_frame:
        if images or videos:
            raise ValueError("Wan 2.7 t2v does not accept reference images or videos")
        if len(audios) > 1:
            raise ValueError(f"Wan 2.7 t2v accepts at most 1 audio; got {len(audios)}")
        command += [
            "text2video", "--model", model,
            "--prompt", prompt, "--ratio", ratio,
        ]
        if audios:
            command += ["--audio", audios[0]]
    elif kind == "i2v" or (kind == "t2v" and first_frame):
        sources = [*images, *videos]
        if first_frame:
            sources.insert(0, first_frame)
        if len(sources) != 1:
            raise ValueError(
                "Wan 2.7 i2v requires exactly 1 source image or video; "
                f"got {len(sources)}"
            )
        if len(audios) > 1:
            raise ValueError(f"Wan 2.7 i2v accepts at most 1 audio; got {len(audios)}")
        if _suffix(sources[0]) in _VIDEO_SUFFIXES:
            raise ValueError(
                "Wan 2.7 frame2video requires an image first frame; "
                "video-extension input is not exposed by installed wan-cli"
            )
        command += [
            "frame2video", "--model", model,
            "--first-frame", sources[0], "--prompt", prompt,
        ]
        if last_frame:
            command += ["--last-frame", last_frame]
        if audios:
            command += ["--audio", audios[0]]
        # frame2video follows its source aspect ratio and rejects --ratio.
    elif kind == "r2v":
        assets = [*images, *videos]
        if not assets:
            raise ValueError("Wan 2.7 r2v requires at least 1 reference asset")
        if len(assets) > 5:
            raise ValueError(f"Wan 2.7 r2v accepts at most 5 assets; got {len(assets)}")
        if audios:
            raise ValueError(
                "Wan 2.7 reference2video does not support audio references; "
                "remove the voice reference or choose wan3.0"
            )
        command += [
            "reference2video", "--model", model,
            "--assets", ",".join(assets), "--prompt", prompt,
        ]
        if first_frame:
            command += ["--first-frame", first_frame]
        else:
            command += ["--ratio", ratio]
        # reference2video follows --first-frame ratio and rejects --ratio with it.
    else:
        raise ValueError(f"unsupported shot kind for Wan 2.7: {kind!r}")

    command += [
        "--duration", str(duration),
        "--resolution", resolution,
        "--wait", "--save", "--save-dir", temp_dir,
        "--timeout", str(timeout), "--output", "json",
    ]
    return command, prompt


def render(
    *,
    kind: str,
    prompt: str,
    media: list[str | Path],
    voice: str | Path | None,
    duration: int,
    out_path: Path,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit one Wan task, wait for it, and place the video at ``out_path``."""
    extra = extra or {}
    resolution = str(extra.get("resolution") or "720P")
    ratio = str(extra.get("ratio") or "16:9")
    audio_output = bool(extra.get("audio_output", True))
    timeout = int(os.environ.get("VIDEOGEN_WAN_TIMEOUT_S", "900"))
    images: list[str] = []
    videos: list[str] = []
    audios: list[str] = []
    for item in media:
        value = str(item)
        if value not in images:
            _append_media(value, images=images, videos=videos, audios=audios)
    if voice:
        audios.append(str(voice))
    first_frame = str(extra.get("first_frame_url") or "").strip() or None
    last_frame = str(extra.get("last_frame_url") or "").strip() or None
    if last_frame and not first_frame:
        raise ValueError("last_frame_url requires first_frame_url")
    model = _video_model()
    effective_images = list(images)
    for frame in (first_frame, last_frame):
        if frame and frame not in effective_images:
            effective_images.append(frame)
    image_limit_values = effective_images if model == "wan3.0" else images
    limits = (
        ("images", image_limit_values, 10),
        ("videos", videos, 5),
        ("audios", audios, 5),
    )
    for label, values, maximum in limits:
        if len(values) > maximum:
            raise ValueError(
                f"Wan video provider accepts at most {maximum} {label}; got {len(values)}"
            )

    duration_floor, duration_ceiling = MODEL_DURATION_LIMITS[model]
    if not duration_floor <= duration <= duration_ceiling:
        raise ValueError(
            f"{model} duration must be in "
            f"[{duration_floor}, {duration_ceiling}] seconds; got {duration}"
        )
    started = time.monotonic()
    repo_root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="spark-video-wan-") as temp_dir:
        upload_cache: dict[str, str] = {}
        images = _upload_local_images(
            images,
            repo_root=repo_root,
            model=model,
            kind=kind,
            timeout=timeout,
            cache=upload_cache,
        )
        videos = _prepare_local_files(
            videos, Path(temp_dir) / "prepared-videos", prefix="video"
        )
        audios = _prepare_local_files(
            audios, Path(temp_dir) / "prepared-audios", prefix="audio"
        )
        if first_frame:
            prepared = _upload_local_images(
                [first_frame],
                repo_root=repo_root,
                model=model,
                kind=kind,
                timeout=timeout,
                cache=upload_cache,
            )
            first_frame = prepared[0]
        if last_frame:
            prepared = _upload_local_images(
                [last_frame],
                repo_root=repo_root,
                model=model,
                kind=kind,
                timeout=timeout,
                cache=upload_cache,
            )
            last_frame = prepared[0]
        cmd, prompt = _build_wan_command(
            repo_root,
            model=model,
            kind=kind,
            prompt=prompt,
            images=images,
            videos=videos,
            audios=audios,
            first_frame=first_frame,
            duration=duration,
            resolution=resolution,
            ratio=ratio,
            temp_dir=temp_dir,
            timeout=timeout,
            audio_output=audio_output,
            last_frame=last_frame,
        )
        version_raw = os.environ.get("SPARK_VIDEO_ATTEMPT", "")
        token = set_context(
            project_id=os.environ.get("SPARK_VIDEO_PROJECT"),
            episode_id=os.environ.get("SPARK_VIDEO_EPISODE"),
            shot_id=os.environ.get("SPARK_VIDEO_SHOT"),
            version=int(version_raw) if version_raw.isdigit() else None,
        )
        try:
            payload = _run(cmd, timeout=timeout)
            log_call(
                kind="video_generate",
                provider="wan-cli",
                model=model,
                endpoint="wan CLI",
                request={"kind": kind, "cmd": cmd},
                response=payload,
                task_id=payload.get("taskId"),
                duration_ms=(time.monotonic() - started) * 1000,
            )
        except Exception as exc:
            log_call(
                kind="video_generate",
                provider="wan-cli",
                model=model,
                endpoint="wan CLI",
                request={"kind": kind, "cmd": cmd},
                duration_ms=(time.monotonic() - started) * 1000,
                error=str(exc),
            )
            raise
        finally:
            reset_context(token)
        if payload.get("ok") is False:
            raise RuntimeError(
                f"wan task {payload.get('taskId', '')} failed: "
                f"{payload.get('errorMsg') or payload.get('statusDescription') or payload}"
            )

        candidates = [
            path for path in _saved_paths(payload)
            if path.exists() and path.suffix.lower() in _VIDEO_SUFFIXES
        ]
        if not candidates:
            candidates = [
                path for path in Path(temp_dir).iterdir()
                if path.is_file() and path.suffix.lower() in _VIDEO_SUFFIXES
            ]
        if not candidates:
            raise RuntimeError(
                "wan finished but returned no saved video; "
                f"taskId={payload.get('taskId', 'unknown')}"
            )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidates[0], out_path)

    return {
        "video_path": str(out_path),
        "provider": "wan-cli",
        "model": model,
        "command": next(
            (
                name
                for name in (
                    "omni2video",
                    "text2video",
                    "frame2video",
                    "reference2video",
                )
                if name in cmd
            ),
            None,
        ),
        "task_id": payload.get("taskId"),
        "elapsed_s": round(time.monotonic() - started, 2),
    }
