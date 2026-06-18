import json as json_mod
import logging
import subprocess
from pathlib import Path
from typing import Optional

from pipeline.media_tools import ffmpeg_bin, ffprobe_bin

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
    logo_path: Optional[Path] = None,
    logo_position_x: float = 0.05,
    logo_position_y: float = 0.03,
    logo_scale: float = 0.15,
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
            logo_path, logo_position_x, logo_position_y, logo_scale,
        )

    return _compose_video_only(
        viz_path, output_path, width, height, max_duration, fade_start,
        logo_path, logo_position_x, logo_position_y, logo_scale,
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


def _video_scale_filter(width, height, fade_start, label="vscaled"):
    return (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fade=t=out:st={fade_start:.2f}:d=1:color=black[{label}]"
    )


def _logo_overlay_filter(width, height, pos_x, pos_y, scale, input_label="vscaled", output_label="vout"):
    logo_w = max(1, int(width * scale))
    x = int(width * pos_x)
    y = int(height * pos_y)
    return (
        f"[1:v]scale={logo_w}:-1[logo];"
        f"[{input_label}][logo]overlay={x}:{y}[{output_label}]"
    )


def _compose_video_only(
    viz_path, output_path, width, height, max_duration, fade_start,
    logo_path=None, logo_position_x=0.05, logo_position_y=0.03, logo_scale=0.15,
):
    """Simple compose: video scale + fade, optional logo, no audio."""
    has_logo = logo_path and logo_path.exists()

    if has_logo:
        vf = _video_scale_filter(width, height, fade_start)
        vf += ";" + _logo_overlay_filter(width, height, logo_position_x, logo_position_y, logo_scale)
        cmd = [ffmpeg_bin(), "-y", "-i", str(viz_path), "-i", str(logo_path)]
        if max_duration > 0:
            cmd.extend(["-t", str(max_duration)])
        cmd.extend(["-filter_complex", vf, "-map", "[vout]", "-an"])
    else:
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"fade=t=out:st={fade_start:.2f}:d=1:color=black"
        )
        cmd = [ffmpeg_bin(), "-y", "-i", str(viz_path)]
        if max_duration > 0:
            cmd.extend(["-t", str(max_duration)])
        cmd.extend(["-vf", vf, "-an"])

    cmd.extend(_encoding_args(output_path))
    return _run_ffmpeg(cmd, output_path, "video-only")


def _compose_bg_audio_only(
    viz_path, output_path, width, height, max_duration, fade_start, bg_audio_path,
    logo_path=None, logo_position_x=0.05, logo_position_y=0.03, logo_scale=0.15,
):
    """Compose with background audio only (no SFX)."""
    has_logo = logo_path and logo_path.exists()
    audio_input_idx = 2 if has_logo else 1

    cmd = [ffmpeg_bin(), "-y", "-i", str(viz_path)]
    if has_logo:
        cmd.extend(["-i", str(logo_path)])
    cmd.extend(["-i", str(bg_audio_path)])

    if max_duration > 0:
        cmd.extend(["-t", str(max_duration)])

    if has_logo:
        vf = _video_scale_filter(width, height, fade_start)
        vf += ";" + _logo_overlay_filter(width, height, logo_position_x, logo_position_y, logo_scale)
        cmd.extend(["-filter_complex", vf, "-map", "[vout]", "-map", f"{audio_input_idx}:a"])
    else:
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"fade=t=out:st={fade_start:.2f}:d=1:color=black"
        )
        cmd.extend(["-vf", vf, "-map", "0:v", "-map", "1:a"])

    cmd.extend(["-c:a", "aac", "-b:a", "192k", "-shortest"])
    cmd.extend(_encoding_args(output_path))
    return _run_ffmpeg(cmd, output_path, "bg audio only")


def _compose_with_audio(
    viz_path, output_path, width, height, max_duration,
    fade_start, duration, bg_audio_path, sfx_hits,
    logo_path=None, logo_position_x=0.05, logo_position_y=0.03, logo_scale=0.15,
):
    """
    Compose with filter_complex: video + SFX one-shots + optional
    background audio all mixed together.

    Input layout:
      0 = video
      1..N = unique SFX files (each may be reused at multiple delays)
      N+1 = background audio (optional)
    """
    if not sfx_hits and bg_audio_path:
        return _compose_bg_audio_only(
            viz_path, output_path, width, height, max_duration,
            fade_start, bg_audio_path,
            logo_path, logo_position_x, logo_position_y, logo_scale,
        )

    has_logo = logo_path and logo_path.exists()

    # Deduplicate SFX files to minimise inputs; map each hit to its input idx
    unique_sfx = {}  # path -> input_idx
    next_idx = 1
    if has_logo:
        next_idx = 2
    for path, _delay in sfx_hits:
        if path not in unique_sfx:
            unique_sfx[path] = next_idx
            next_idx += 1

    cmd = [ffmpeg_bin(), "-y", "-i", str(viz_path)]
    if has_logo:
        cmd.extend(["-i", str(logo_path)])
    for path in unique_sfx:
        cmd.extend(["-i", str(path)])

    bg_idx = None
    if bg_audio_path:
        bg_idx = next_idx
        cmd.extend(["-i", str(bg_audio_path)])

    if max_duration > 0:
        cmd.extend(["-t", str(max_duration)])

    # Build filter_complex
    if has_logo:
        vf = _video_scale_filter(width, height, fade_start, label="vscaled")
        vf += ";" + _logo_overlay_filter(
            width, height, logo_position_x, logo_position_y, logo_scale,
            input_label="vscaled", output_label="vout",
        )
    else:
        vf = _video_scale_filter(width, height, fade_start, label="vout")
    video_out = "[vout]"
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
        audio_map = sfx_out

    filter_complex = ";\n".join(filters)

    cmd.extend(["-filter_complex", filter_complex])
    cmd.extend(["-map", video_out, "-map", audio_map])
    cmd.extend(["-c:a", "aac", "-b:a", "192k"])
    cmd.extend(_encoding_args(output_path))
    return _run_ffmpeg(cmd, output_path, f"{len(sfx_hits)} SFX hits")


def _encoding_args(output_path):
    return [
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "10",
        "-pix_fmt", "yuv420p",
        "-r", "60",
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
        ffprobe_bin(), "-v", "quiet",
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
