import json as json_mod
import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

EVENT_TYPE_TO_SFX = {
    "entry": "sfx_entry",
    "zone": "sfx_zone",
    "score_totals": "sfx_score_totals",
    "stats": "sfx_stats",
}


def compose_story_video(
    viz_path: Path,
    output_path: Path,
    audio_path: Optional[Path] = None,
    width: int = 1080,
    height: int = 1920,
    max_duration: float = 60.0,
    sfx_paths: Optional[dict] = None,
    scene_events: Optional[list] = None,
    **kwargs,
) -> Path:
    """
    Compose a 9:16 story video with fade-to-black, optional background
    audio, and one-shot SFX placed at scene event timestamps.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration = _get_video_duration(viz_path)
    if max_duration > 0:
        duration = min(duration, max_duration)
    fade_start = max(0, duration - 1.0)

    sfx_hits = _build_sfx_hits(sfx_paths or {}, scene_events or [])
    has_sfx = bool(sfx_hits)
    has_bg = audio_path and audio_path.exists()

    if has_sfx or has_bg:
        return _compose_with_audio(
            viz_path, output_path, width, height, max_duration,
            fade_start, duration, audio_path if has_bg else None,
            sfx_hits,
        )

    return _compose_video_only(
        viz_path, output_path, width, height, max_duration, fade_start,
    )


def _build_sfx_hits(sfx_paths: dict, scene_events: list) -> list:
    """
    Match scene events to SFX files. Returns a list of
    (sfx_path, delay_ms) tuples, deduplicated by file for efficient
    ffmpeg input handling.
    """
    hits = []
    for evt in scene_events:
        slot = EVENT_TYPE_TO_SFX.get(evt.get("type", ""))
        path = sfx_paths.get(slot)
        if path and path.exists():
            delay_ms = max(0, int(evt["t"] * 1000))
            hits.append((path, delay_ms))
    return hits


def _compose_video_only(viz_path, output_path, width, height, max_duration, fade_start):
    """Simple compose: video scale + fade, no audio."""
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fade=t=out:st={fade_start:.2f}:d=1:color=black"
    )
    cmd = ["ffmpeg", "-y", "-i", str(viz_path)]
    if max_duration > 0:
        cmd.extend(["-t", str(max_duration)])
    cmd.extend(["-vf", vf, "-an"])
    cmd.extend(_encoding_args(output_path))
    return _run_ffmpeg(cmd, output_path, "video-only")


def _compose_with_audio(
    viz_path, output_path, width, height, max_duration,
    fade_start, duration, bg_audio_path, sfx_hits,
):
    """
    Compose with filter_complex: video + SFX one-shots + optional
    background audio all mixed together.

    Input layout:
      0 = video
      1..N = unique SFX files (each may be reused at multiple delays)
      N+1 = background audio (optional)
    """
    # Deduplicate SFX files to minimise inputs; map each hit to its input idx
    unique_sfx = {}  # path -> input_idx
    next_idx = 1
    for path, _delay in sfx_hits:
        if path not in unique_sfx:
            unique_sfx[path] = next_idx
            next_idx += 1

    cmd = ["ffmpeg", "-y", "-i", str(viz_path)]
    for path in unique_sfx:
        cmd.extend(["-i", str(path)])

    bg_idx = None
    if bg_audio_path:
        bg_idx = next_idx
        cmd.extend(["-i", str(bg_audio_path)])

    if max_duration > 0:
        cmd.extend(["-t", str(max_duration)])

    # Build filter_complex
    vf = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fade=t=out:st={fade_start:.2f}:d=1:color=black[vout]"
    )
    filters = [vf]

    # Delay each SFX hit
    sfx_labels = []
    for i, (path, delay_ms) in enumerate(sfx_hits):
        inp = unique_sfx[path]
        label = f"sfx{i}"
        filters.append(f"[{inp}:a]adelay={delay_ms}|{delay_ms}[{label}]")
        sfx_labels.append(f"[{label}]")

    # Mix all SFX together
    if len(sfx_labels) == 1:
        sfx_out = sfx_labels[0]
    else:
        mix_in = "".join(sfx_labels)
        filters.append(f"{mix_in}amix=inputs={len(sfx_labels)}:normalize=0[sfx_mix]")
        sfx_out = "[sfx_mix]"

    # Mix with background audio if present
    if bg_idx is not None:
        filters.append(
            f"[{bg_idx}:a]{sfx_out}amix=inputs=2:weights=1 0.8:normalize=0[aout]"
        )
        audio_map = "[aout]"
    else:
        if sfx_out.startswith("[") and sfx_out.endswith("]"):
            audio_map = sfx_out
        else:
            audio_map = sfx_out

    filter_complex = ";\n".join(filters)

    cmd.extend(["-filter_complex", filter_complex])
    cmd.extend(["-map", "[vout]", "-map", audio_map])
    cmd.extend(["-c:a", "aac", "-b:a", "192k"])
    cmd.extend(_encoding_args(output_path))
    return _run_ffmpeg(cmd, output_path, f"{len(sfx_hits)} SFX hits")


def _encoding_args(output_path):
    return [
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "15",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        str(output_path),
    ]


def _run_ffmpeg(cmd, output_path, label):
    logger.info("Running ffmpeg compose (%s)", label)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg compose failed: {result.stderr[:1000]}")
    logger.info("Composed story saved to %s (%.1f MB)", output_path, output_path.stat().st_size / 1e6)
    return output_path


def _get_video_duration(path: Path) -> float:
    """Get video duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json_mod.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                return float(stream.get("duration", 30))
    except Exception:
        logger.warning("ffprobe failed for %s, assuming 30s", path)
    return 30.0
