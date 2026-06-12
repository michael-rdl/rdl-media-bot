import json as json_mod
import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def compose_story_video(
    viz_path: Path,
    output_path: Path,
    audio_path: Optional[Path] = None,
    width: int = 1080,
    height: int = 1920,
    max_duration: float = 60.0,
    **kwargs,
) -> Path:
    """
    Compose a 9:16 story video. Scales the viz capture to fit, then
    adds a 1-second fade-to-black at the end. Text overlays are
    handled by the video-out page itself.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration = _get_video_duration(viz_path)
    if max_duration > 0:
        duration = min(duration, max_duration)
    fade_start = max(0, duration - 1.0)

    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fade=t=out:st={fade_start:.2f}:d=1:color=black"
    )

    cmd = ["ffmpeg", "-y", "-i", str(viz_path)]

    if audio_path and audio_path.exists():
        cmd.extend(["-i", str(audio_path)])
        audio_idx = 1
    else:
        audio_idx = None

    if max_duration > 0:
        cmd.extend(["-t", str(max_duration)])

    cmd.extend(["-vf", vf])

    if audio_idx is not None:
        cmd.extend(["-map", "0:v", "-map", f"{audio_idx}:a"])
        cmd.extend(["-c:a", "aac", "-b:a", "192k", "-shortest"])
    else:
        cmd.extend(["-an"])

    cmd.extend([
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "15",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        str(output_path),
    ])

    logger.info("Running ffmpeg compose (fade-to-black at %.1fs)", fade_start)
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
