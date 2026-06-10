import logging
from pathlib import Path

from django.conf import settings

from pipeline.models import ContentPiece, Job
from pipeline.rdl_client import api_get

from .browser import capture_replay

logger = logging.getLogger(__name__)


def capture_visualiser(job_id: int):
    """
    Fetch run metadata from rdl-base, then capture the Three.js
    visualiser replay as an MP4 video.
    """
    job = Job.objects.get(id=job_id)

    run_data = _fetch_run_metadata(job.rdl_run_id)
    job.run_metadata = run_data
    job.save(update_fields=["run_metadata"])

    duration = _estimate_duration(run_data)
    logger.info("Job #%d: estimated run duration = %.1fs", job_id, duration)

    media_root = Path(settings.MEDIA_ROOT)
    job_dir = media_root / "jobs" / str(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    output_path = job_dir / "viz_capture.mp4"

    capture_replay(job.rdl_run_id, output_path, duration)

    file_size = output_path.stat().st_size
    probe = _probe_video(output_path)

    with open(output_path, "rb") as f:
        piece = ContentPiece.objects.create(
            job=job,
            piece_type=ContentPiece.PieceType.VIZ_CAPTURE,
            mime_type="video/mp4",
            duration_seconds=probe.get("duration", duration),
            width=probe.get("width", 1920),
            height=probe.get("height", 1080),
            file_size_bytes=file_size,
        )
        relative_path = f"jobs/{job_id}/viz_capture.mp4"
        piece.file.name = relative_path
        piece.save(update_fields=["file"])

    logger.info("Job #%d: viz capture saved as ContentPiece #%d", job_id, piece.id)


def _fetch_run_metadata(run_id: int) -> dict:
    resp = api_get(f"/run/{run_id}/")
    resp.raise_for_status()
    return resp.json()


def _estimate_duration(run_data: dict) -> float:
    """Estimate the replay duration from telemetry data."""
    from datetime import datetime

    for side in ("left_run_data", "right_run_data"):
        rd = run_data.get(side)
        if not rd:
            continue
        telemetry = rd.get("telemetry", [])
        if not telemetry:
            continue

        time_vals = [p.get("t") for p in telemetry if p.get("t") is not None]
        if not time_vals:
            continue

        sample = time_vals[0]
        if isinstance(sample, str) and "T" in sample:
            parsed = [datetime.fromisoformat(t) for t in time_vals]
            duration = (max(parsed) - min(parsed)).total_seconds()
        else:
            floats = [float(t) for t in time_vals]
            duration = max(floats) - min(floats)

        if duration > 0:
            return float(duration)

    return 30.0


def _probe_video(path: Path) -> dict:
    """Use ffprobe to get video dimensions and duration."""
    import subprocess
    import json as json_mod

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
        logger.warning("ffprobe failed for %s", path)

    return {}
