import logging
from pathlib import Path

from django.conf import settings

from pipeline.models import ContentPiece, ContentTemplate, Job

from .editor import compose_story_video

logger = logging.getLogger(__name__)


def compose_story(job_id: int):
    """
    Compose a 9:16 story video from the captured viz and extracted audio.
    Uses the job's ContentTemplate for layout configuration.
    """
    job = Job.objects.get(id=job_id)

    viz_piece = job.pieces.filter(
        piece_type=ContentPiece.PieceType.VIZ_CAPTURE
    ).first()

    if not viz_piece or not viz_piece.file:
        raise RuntimeError("No viz capture found for this job")

    audio_piece = job.pieces.filter(
        piece_type=ContentPiece.PieceType.AUDIO_EXTRACT
    ).first()

    template = job.template or ContentTemplate(
        output_width=1080,
        output_height=1920,
        max_duration_seconds=60,
        font_family="Arial",
        font_size=48,
        font_color="white",
    )

    media_root = Path(settings.MEDIA_ROOT)
    viz_path = media_root / viz_piece.file.name
    audio_path = media_root / audio_piece.file.name if audio_piece and audio_piece.file else None
    output_path = media_root / "jobs" / str(job_id) / "story_final.mp4"

    stats = _extract_stats(job.run_metadata)

    logo_path = Path(template.logo_path) if template.logo_path else None

    compose_story_video(
        viz_path=viz_path,
        output_path=output_path,
        audio_path=audio_path,
        width=template.output_width,
        height=template.output_height,
        max_duration=float(template.max_duration_seconds),
        driver_name=job.driver_name,
        run_number=job.run_number,
        stats=stats,
        logo_path=logo_path,
        font_family=template.font_family,
        font_size=template.font_size,
        font_color=template.font_color,
    )

    file_size = output_path.stat().st_size
    probe = _probe_video(output_path)

    story_piece = ContentPiece.objects.create(
        job=job,
        piece_type=ContentPiece.PieceType.COMPOSED_STORY,
        mime_type="video/mp4",
        duration_seconds=probe.get("duration"),
        width=probe.get("width", template.output_width),
        height=probe.get("height", template.output_height),
        file_size_bytes=file_size,
    )
    story_piece.file.name = f"jobs/{job_id}/story_final.mp4"
    story_piece.save(update_fields=["file"])

    logger.info("Job #%d: composed story saved as ContentPiece #%d", job_id, story_piece.id)


def _extract_stats(run_metadata: dict) -> dict:
    """Pull key stats from rdl-base run metadata for overlay display."""
    stats = {}

    for side in ("left_run_data", "right_run_data"):
        rd = run_metadata.get(side)
        if not rd:
            continue
        telemetry = rd.get("telemetry", [])
        if not telemetry:
            continue

        speeds = []
        angles = []
        for p in telemetry:
            s = p.get("s")
            a = p.get("a")
            if s is not None:
                speeds.append(float(s))
            if a is not None:
                angles.append(abs(float(a)))

        if speeds:
            stats["max_speed"] = max(speeds)
        if angles:
            stats["max_drift_angle"] = max(angles)
        break

    if "score" in run_metadata:
        stats["score"] = float(run_metadata["score"])
    elif "total_score" in run_metadata:
        stats["score"] = float(run_metadata["total_score"])

    return stats


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
