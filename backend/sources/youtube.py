import logging
import subprocess
from pathlib import Path
from typing import Optional

from .base import ContentSource

from pipeline.media_tools import ffmpeg_bin

logger = logging.getLogger(__name__)


class YouTubeSource(ContentSource):
    """Fetch clips from YouTube streams/VODs using yt-dlp."""

    def fetch_clip(
        self,
        url: str,
        output_dir: Path,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "stream_clip.mp4"

        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
        ]

        if start_time is not None and end_time is not None:
            section = f"*{_format_time(start_time)}-{_format_time(end_time)}"
            cmd.extend(["--download-sections", section])
            cmd.append("--force-keyframes-at-cuts")

        cmd.extend(["-o", str(output_path), url])

        logger.info("Running yt-dlp: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            raise RuntimeError(f"yt-dlp failed: {result.stderr[:1000]}")

        if not output_path.exists():
            candidates = list(output_dir.glob("stream_clip.*"))
            if candidates:
                output_path = candidates[0]
            else:
                raise RuntimeError(f"yt-dlp produced no output in {output_dir}")

        logger.info("Stream clip saved to %s (%.1f MB)", output_path, output_path.stat().st_size / 1e6)
        return output_path

    def extract_audio(self, video_path: Path, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            ffmpeg_bin(), "-y",
            "-i", str(video_path),
            "-vn",
            "-acodec", "aac",
            "-b:a", "192k",
            str(output_path),
        ]

        logger.info("Extracting audio from %s", video_path)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg audio extract failed: {result.stderr[:500]}")

        logger.info("Audio saved to %s", output_path)
        return output_path


def _format_time(seconds: float) -> str:
    """Format seconds into HH:MM:SS.ss for yt-dlp."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:05.2f}"
