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
    Compose a 9:16 story video from a visualiser capture and optional audio.
    Scales/pads to target resolution and mixes audio if provided.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    inputs = ["-i", str(viz_path)]

    if audio_path and audio_path.exists():
        inputs.extend(["-i", str(audio_path)])
        audio_input_idx = 1
    else:
        audio_input_idx = None

    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
    )

    cmd = ["ffmpeg", "-y"]
    cmd.extend(inputs)

    if max_duration > 0:
        cmd.extend(["-t", str(max_duration)])

    cmd.extend(["-vf", vf])

    if audio_input_idx is not None:
        cmd.extend(["-map", "0:v", "-map", f"{audio_input_idx}:a"])
        cmd.extend(["-c:a", "aac", "-b:a", "192k", "-shortest"])
    else:
        cmd.extend(["-an"])

    cmd.extend([
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        str(output_path),
    ])

    logger.info("Running ffmpeg compose: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg compose failed: {result.stderr[:1000]}")

    logger.info("Composed story saved to %s (%.1f MB)", output_path, output_path.stat().st_size / 1e6)
    return output_path
