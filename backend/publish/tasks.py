import logging
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from pipeline.models import ContentPiece, Job, PublishResult

logger = logging.getLogger(__name__)


def publish_content(job_id: int):
    """
    Publish the composed story to configured platforms.
    Currently supports Instagram (Stories/Reels) and YouTube (Shorts).
    """
    job = Job.objects.get(id=job_id)

    story_piece = job.pieces.filter(
        piece_type=ContentPiece.PieceType.COMPOSED_STORY
    ).first()

    if not story_piece or not story_piece.file:
        raise RuntimeError("No composed story found for this job")

    media_root = Path(settings.MEDIA_ROOT)
    video_path = media_root / story_piece.file.name

    caption = _build_caption(job)

    if settings.INSTAGRAM_ACCESS_TOKEN:
        _publish_instagram_graph(job, story_piece, video_path, caption)
    elif settings.INSTAGRAM_USERNAME:
        _publish_instagram_private(job, story_piece, video_path, caption)
    else:
        logger.warning("Job #%d: no Instagram credentials configured, skipping", job_id)

    if settings.YOUTUBE_OAUTH_TOKEN_FILE:
        _publish_youtube(job, story_piece, video_path, caption)
    else:
        logger.warning("Job #%d: no YouTube credentials configured, skipping", job_id)


def _publish_instagram_graph(job, story_piece, video_path, caption):
    from .instagram import InstagramGraphPublisher

    media_type = "REELS" if job.publish_as_reel else "STORIES"
    platform = (
        PublishResult.Platform.INSTAGRAM_REEL
        if job.publish_as_reel
        else PublishResult.Platform.INSTAGRAM_STORY
    )

    pr = PublishResult.objects.create(
        content_piece=story_piece,
        platform=platform,
        status=PublishResult.Status.UPLOADING,
        caption=caption,
    )

    try:
        publisher = InstagramGraphPublisher()
        result = publisher.publish(
            video_path, caption, media_type=media_type,
        )
        pr.status = PublishResult.Status.PUBLISHED
        pr.platform_post_id = result["post_id"]
        pr.platform_url = result.get("url", "")
        pr.published_at = timezone.now()
        pr.save()
        logger.info("Job #%d: published to IG (%s): %s", job.id, media_type, result.get("url"))
    except Exception as exc:
        pr.status = PublishResult.Status.FAILED
        pr.error_message = str(exc)[:2000]
        pr.save()
        logger.exception("Job #%d: IG publish failed", job.id)
        raise


def _publish_instagram_private(job, story_piece, video_path, caption):
    from .instagram import InstagrapiPublisher

    media_type = "REELS" if job.publish_as_reel else "STORIES"
    platform = (
        PublishResult.Platform.INSTAGRAM_REEL
        if job.publish_as_reel
        else PublishResult.Platform.INSTAGRAM_STORY
    )

    pr = PublishResult.objects.create(
        content_piece=story_piece,
        platform=platform,
        status=PublishResult.Status.UPLOADING,
        caption=caption,
    )

    try:
        publisher = InstagrapiPublisher()
        result = publisher.publish(
            video_path, caption, media_type=media_type,
        )
        pr.status = PublishResult.Status.PUBLISHED
        pr.platform_post_id = result["post_id"]
        pr.platform_url = result.get("url", "")
        pr.published_at = timezone.now()
        pr.save()
        logger.info("Job #%d: published to IG via instagrapi: %s", job.id, result.get("url"))
    except Exception as exc:
        pr.status = PublishResult.Status.FAILED
        pr.error_message = str(exc)[:2000]
        pr.save()
        logger.exception("Job #%d: IG instagrapi publish failed", job.id)
        raise


def _publish_youtube(job, story_piece, video_path, caption):
    from .youtube import YouTubePublisher

    pr = PublishResult.objects.create(
        content_piece=story_piece,
        platform=PublishResult.Platform.YOUTUBE_SHORT,
        status=PublishResult.Status.UPLOADING,
        caption=caption,
    )

    try:
        publisher = YouTubePublisher()
        title = f"{job.driver_name} - Run {job.run_number}" if job.driver_name else f"Run {job.run_number}"
        result = publisher.publish(
            video_path,
            caption,
            title=title,
            is_short=True,
        )
        pr.status = PublishResult.Status.PUBLISHED
        pr.platform_post_id = result["post_id"]
        pr.platform_url = result.get("url", "")
        pr.published_at = timezone.now()
        pr.save()
        logger.info("Job #%d: published to YouTube: %s", job.id, result.get("url"))
    except Exception as exc:
        pr.status = PublishResult.Status.FAILED
        pr.error_message = str(exc)[:2000]
        pr.save()
        logger.exception("Job #%d: YouTube publish failed", job.id)
        raise


def _build_caption(job) -> str:
    parts = []

    if job.driver_name:
        parts.append(job.driver_name)

    if job.run_number:
        parts.append(f"Run {job.run_number}")

    stats = _extract_stats(job.run_metadata)
    if stats.get("max_speed"):
        parts.append(f"Top Speed: {stats['max_speed']:.0f} km/h")
    if stats.get("max_drift_angle"):
        parts.append(f"Max Angle: {stats['max_drift_angle']:.1f}°")

    parts.append("")
    parts.append("#drift #motorsport #racedatalabs #rdl")

    return " | ".join(p for p in parts if p) if parts else "Race Data Labs"


def _extract_stats(run_metadata: dict) -> dict:
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
    return stats
