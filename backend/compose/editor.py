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
    driver_name: str = "",
    run_number: str = "",
    stats: Optional[dict] = None,
    logo_path: Optional[Path] = None,
    font_family: str = "Arial",
    font_size: int = 48,
    font_color: str = "white",
) -> Path:
    """
    Compose a 9:16 story video from a visualiser capture and optional audio.

    Applies:
    - Scale/pad to 9:16 (1080x1920)
    - Driver name + run number text overlay
    - Stats overlay (speed, angle, score)
    - Logo overlay if provided
    - Audio mix from stream clip
    - Duration trim
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    filter_parts = []
    inputs = ["-i", str(viz_path)]
    input_idx = 0

    if audio_path and audio_path.exists():
        inputs.extend(["-i", str(audio_path)])
        audio_input_idx = 1
    else:
        audio_input_idx = None

    # Scale and pad the viz capture to 9:16 portrait
    filter_parts.append(
        f"[{input_idx}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black[base]"
    )

    current_label = "base"

    if logo_path and Path(logo_path).exists():
        logo_input_idx = len(inputs) // 2
        inputs.extend(["-i", str(logo_path)])

        logo_w = int(width * 0.15)
        logo_x = int(width * 0.05)
        logo_y = int(height * 0.03)

        filter_parts.append(
            f"[{logo_input_idx}:v]scale={logo_w}:-1[logo]"
        )
        filter_parts.append(
            f"[{current_label}][logo]overlay={logo_x}:{logo_y}[withlogo]"
        )
        current_label = "withlogo"

    text_filters = []
    if driver_name:
        escaped_name = _escape_drawtext(driver_name)
        text_filters.append(
            f"drawtext=text='{escaped_name}'"
            f":fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            f":fontsize={font_size}:fontcolor={font_color}"
            f":borderw=3:bordercolor=black"
            f":x=(w-text_w)/2:y=h*0.85"
        )

    if run_number:
        escaped_run = _escape_drawtext(f"Run {run_number}")
        text_filters.append(
            f"drawtext=text='{escaped_run}'"
            f":fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            f":fontsize={int(font_size * 0.7)}:fontcolor={font_color}"
            f":borderw=2:bordercolor=black"
            f":x=(w-text_w)/2:y=h*0.90"
        )

    if stats:
        stats_lines = _build_stats_text(stats)
        if stats_lines:
            escaped_stats = _escape_drawtext(stats_lines)
            text_filters.append(
                f"drawtext=text='{escaped_stats}'"
                f":fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
                f":fontsize={int(font_size * 0.5)}:fontcolor={font_color}"
                f":borderw=2:bordercolor=black"
                f":x=w*0.05:y=h*0.08"
            )

    if text_filters:
        text_chain = ",".join(text_filters)
        filter_parts.append(f"[{current_label}]{text_chain}[final]")
        current_label = "final"

    filter_complex = ";".join(filter_parts)

    cmd = ["ffmpeg", "-y"]
    cmd.extend(inputs)

    if max_duration > 0:
        cmd.extend(["-t", str(max_duration)])

    cmd.extend(["-filter_complex", filter_complex])
    cmd.extend(["-map", f"[{current_label}]"])

    if audio_input_idx is not None:
        cmd.extend(["-map", f"{audio_input_idx}:a"])
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


def _escape_drawtext(text: str) -> str:
    """Escape special characters for ffmpeg drawtext filter."""
    return (
        text.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace("%", "%%")
    )


def _build_stats_text(stats: dict) -> str:
    """Build a multi-line stats string from run data."""
    lines = []
    if "max_speed" in stats:
        lines.append(f"Top Speed: {stats['max_speed']:.0f} km/h")
    if "max_drift_angle" in stats:
        lines.append(f"Max Angle: {stats['max_drift_angle']:.1f}°")
    if "score" in stats:
        lines.append(f"Score: {stats['score']:.1f}")
    return "\n".join(lines)
