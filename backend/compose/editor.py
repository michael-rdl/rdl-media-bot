import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

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
    **kwargs,
) -> Path:
    """
    Compose a 9:16 story video with text overlays burned in via Pillow.

    1. Generate a transparent PNG overlay with text/logo
    2. Use ffmpeg to scale video + overlay the PNG
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    overlay_path = output_path.parent / "overlay.png"
    _create_overlay(
        overlay_path, width, height,
        driver_name=driver_name,
        run_number=run_number,
        stats=stats,
        logo_path=logo_path,
    )

    inputs = ["-i", str(viz_path), "-i", str(overlay_path)]

    if audio_path and audio_path.exists():
        inputs.extend(["-i", str(audio_path)])
        audio_idx = 2
    else:
        audio_idx = None

    filter_complex = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black[bg];"
        f"[bg][1:v]overlay=0:0[out]"
    )

    cmd = ["ffmpeg", "-y"]
    cmd.extend(inputs)

    if max_duration > 0:
        cmd.extend(["-t", str(max_duration)])

    cmd.extend(["-filter_complex", filter_complex])
    cmd.extend(["-map", "[out]"])

    if audio_idx is not None:
        cmd.extend(["-map", f"{audio_idx}:a"])
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

    logger.info("Running ffmpeg compose with overlay")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    overlay_path.unlink(missing_ok=True)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg compose failed: {result.stderr[:1000]}")

    logger.info("Composed story saved to %s (%.1f MB)", output_path, output_path.stat().st_size / 1e6)
    return output_path


def _create_overlay(
    output_path: Path,
    width: int,
    height: int,
    driver_name: str = "",
    run_number: str = "",
    stats: Optional[dict] = None,
    logo_path: Optional[Path] = None,
):
    """Create a transparent PNG overlay with text and optional logo."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_large = _load_font(54)
    font_medium = _load_font(38)
    font_small = _load_font(28)

    y_bottom = int(height * 0.82)

    # Semi-transparent bar at bottom for text
    if driver_name or run_number:
        bar_top = y_bottom - 20
        bar_bottom = min(y_bottom + 140, height)
        draw.rectangle(
            [(0, bar_top), (width, bar_bottom)],
            fill=(0, 0, 0, 150),
        )

    # Driver name
    if driver_name:
        bbox = draw.textbbox((0, 0), driver_name, font=font_large)
        text_w = bbox[2] - bbox[0]
        x = (width - text_w) // 2
        draw.text((x, y_bottom), driver_name, font=font_large, fill=(255, 255, 255, 255))
        y_bottom += 60

    # Run number
    if run_number:
        run_text = f"Run {run_number}"
        bbox = draw.textbbox((0, 0), run_text, font=font_medium)
        text_w = bbox[2] - bbox[0]
        x = (width - text_w) // 2
        draw.text((x, y_bottom), run_text, font=font_medium, fill=(200, 200, 200, 230))

    # Stats in top-left
    if stats:
        y_stats = int(height * 0.06)
        stat_lines = []
        if "max_speed" in stats:
            stat_lines.append(f"Top Speed: {stats['max_speed']:.0f} km/h")
        if "max_drift_angle" in stats:
            stat_lines.append(f"Max Angle: {stats['max_drift_angle']:.1f}\u00b0")
        if "score" in stats:
            stat_lines.append(f"Score: {stats['score']:.1f}")

        if stat_lines:
            padding = 15
            line_height = 36
            box_w = 320
            box_h = len(stat_lines) * line_height + padding * 2

            draw.rectangle(
                [(30, y_stats - padding), (30 + box_w, y_stats + box_h - padding)],
                fill=(0, 0, 0, 150),
            )

            for line in stat_lines:
                draw.text((45, y_stats), line, font=font_small, fill=(255, 255, 255, 230))
                y_stats += line_height

    # Logo
    if logo_path and Path(logo_path).exists():
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo_w = int(width * 0.15)
            logo_h = int(logo.height * (logo_w / logo.width))
            logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
            img.paste(logo, (int(width * 0.05), int(height * 0.02)), logo)
        except Exception:
            logger.warning("Failed to load logo from %s", logo_path)

    img.save(str(output_path), "PNG")
    logger.info("Created overlay %dx%d at %s", width, height, output_path)


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """Load a font, trying common macOS/Linux paths."""
    font_paths = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSText.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in font_paths:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()
