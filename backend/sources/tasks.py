import logging
from pathlib import Path

from django.conf import settings

from pipeline.models import ContentPiece, Job

from .youtube import YouTubeSource

logger = logging.getLogger(__name__)


def clip_youtube_stream(job_id: int):
    """
    Download a clip from the configured YouTube stream source
    and extract its audio track.
    """
    job = Job.objects.get(id=job_id)

    if not job.stream_source:
        raise RuntimeError("No stream source configured for this job")

    stream_url = job.stream_source.url
    start_time, end_time = _calculate_time_window(job)

    media_root = Path(settings.MEDIA_ROOT)
    job_dir = media_root / "jobs" / str(job_id)

    source = YouTubeSource()

    clip_path = source.fetch_clip(
        url=stream_url,
        output_dir=job_dir,
        start_time=start_time,
        end_time=end_time,
    )

    clip_size = clip_path.stat().st_size
    clip_probe = _probe_video(clip_path)

    clip_piece = ContentPiece.objects.create(
        job=job,
        piece_type=ContentPiece.PieceType.STREAM_CLIP,
        mime_type="video/mp4",
        duration_seconds=clip_probe.get("duration"),
        width=clip_probe.get("width"),
        height=clip_probe.get("height"),
        file_size_bytes=clip_size,
    )
    clip_piece.file.name = f"jobs/{job_id}/{clip_path.name}"
    clip_piece.save(update_fields=["file"])

    audio_path = job_dir / "stream_audio.m4a"
    source.extract_audio(clip_path, audio_path)

    audio_piece = ContentPiece.objects.create(
        job=job,
        piece_type=ContentPiece.PieceType.AUDIO_EXTRACT,
        mime_type="audio/mp4",
        file_size_bytes=audio_path.stat().st_size,
    )
    audio_piece.file.name = f"jobs/{job_id}/stream_audio.m4a"
    audio_piece.save(update_fields=["file"])

    logger.info(
        "Job #%d: stream clip (piece #%d) and audio (piece #%d) created",
        job_id, clip_piece.id, audio_piece.id,
    )


def _calculate_time_window(job):
    """
    Determine the start/end timestamps to clip from the stream.
    Returns (start_seconds, end_seconds) relative to stream start,
    or (None, None) if we can't determine the window.

    Note: for live stream VODs, this would need the stream start time
    to compute offsets. For now, returns None to download the full
    stream/VOD and let the compose stage handle trimming.
    """
    return None, None


def _probe_video(path: Path) -> dict:
    import json as json_mod
    import subprocess

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
                return {
                    "width": int(stream.get("width", 0)),
                    "height": int(stream.get("height", 0)),
                    "duration": float(stream.get("duration", 0)),
                }
    except Exception:
        pass
    return {}
