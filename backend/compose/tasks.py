import logging
from pathlib import Path

from django.conf import settings

from pipeline.models import ContentPiece, ContentTemplate, Event, Job

from .editor import compose_story_video

logger = logging.getLogger(__name__)

SFX_FIELDS = ("sfx_entry", "sfx_zone", "sfx_score_totals", "sfx_stats")


def _resolve_sfx_paths(event):
    """Return {slot: Path} for each SFX slot, falling back to the most recent event."""
    paths = {}
    for slot in SFX_FIELDS:
        f = getattr(event, slot)
        if f:
            paths[slot] = Path(f.path)
        else:
            fallback = (
                Event.objects.filter(**{f"{slot}__gt": ""})
                .exclude(id=event.id)
                .order_by("-created_at")
                .first()
            )
            if fallback:
                fb = getattr(fallback, slot)
                if fb:
                    paths[slot] = Path(fb.path)
    return paths


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

    audio_path = None
    if audio_piece and audio_piece.file:
        audio_path = media_root / audio_piece.file.name
    elif job.session and job.session.event.audio_file:
        audio_path = Path(job.session.event.audio_file.path)
        logger.info("Job #%d: using event-level audio: %s", job_id, audio_path)
    output_path = media_root / "jobs" / str(job_id) / "story_final.mp4"

    # Resolve SFX one-shots and scene event timestamps
    sfx_paths = {}
    scene_events = viz_piece.metadata.get("scene_events", [])
    if job.session:
        sfx_paths = _resolve_sfx_paths(job.session.event)
        if sfx_paths:
            logger.info("Job #%d: SFX paths: %s", job_id, list(sfx_paths.keys()))
        if scene_events:
            logger.info("Job #%d: scene events: %s", job_id, scene_events)

    compose_story_video(
        viz_path=viz_path,
        output_path=output_path,
        audio_path=audio_path,
        width=template.output_width,
        height=template.output_height,
        max_duration=float(template.max_duration_seconds),
        sfx_paths=sfx_paths,
        scene_events=scene_events,
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


def _extract_instagram_handles(run_metadata: dict) -> list[str]:
    handles = []
    for side in ("left_run_data", "right_run_data"):
        rd = run_metadata.get(side)
        if not rd or not rd.get("driver"):
            continue
        handle = rd["driver"].get("instagram_handle", "")
        if handle:
            handles.append(handle)
    return handles


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
