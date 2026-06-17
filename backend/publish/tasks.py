import logging
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone

from pipeline.models import ContentPiece, Event, Job, PublishResult
from pipeline.rdl_client import get_config
from pipeline.utils import resolve_organisation_for_job
from publish.instagram_credentials import get_instagram_credentials

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
    ig_handles = _extract_instagram_handles(job.run_metadata)
    organisation = resolve_organisation_for_job(job)
    org_handle = organisation.instagram_handle.lstrip("@") if organisation and organisation.instagram_handle else ""
    if org_handle and org_handle not in ig_handles:
        ig_handles = [org_handle, *ig_handles]

    ig_post_id = None
    ig_creds = get_instagram_credentials(organisation)
    if ig_creds and ig_creds.method == "graph":
        ig_post_id = _publish_instagram_graph(job, story_piece, video_path, caption, ig_creds)
    elif ig_creds and ig_creds.method == "instagrapi":
        ig_post_id = _publish_instagram_private(job, story_piece, video_path, caption, ig_handles, organisation, ig_creds)
    else:
        logger.warning("Job #%d: no Instagram credentials configured, skipping", job_id)

    if ig_post_id and not job.publish_as_reel:
        _add_to_event_highlight(job, ig_post_id, ig_creds)

    if settings.YOUTUBE_OAUTH_TOKEN_FILE:
        _publish_youtube(job, story_piece, video_path, caption)
    else:
        logger.warning("Job #%d: no YouTube credentials configured, skipping", job_id)

    _maybe_publish_ad(job, story_piece)


def _publish_instagram_graph(job, story_piece, video_path, caption, credentials):
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
        publisher = InstagramGraphPublisher(credentials)
        result = publisher.publish(
            video_path, caption, media_type=media_type,
        )
        pr.status = PublishResult.Status.PUBLISHED
        pr.platform_post_id = result["post_id"]
        pr.platform_url = result.get("url", "")
        pr.published_at = timezone.now()
        pr.save()
        logger.info("Job #%d: published to IG (%s): %s", job.id, media_type, result.get("url"))
        return result["post_id"]
    except Exception as exc:
        pr.status = PublishResult.Status.FAILED
        pr.error_message = str(exc)[:2000]
        pr.save()
        logger.exception("Job #%d: IG publish failed", job.id)
        raise


def _publish_instagram_private(job, story_piece, video_path, caption, ig_handles=None, organisation=None, credentials=None):
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

    config = get_config(organisation)
    replay_url = f"{config.base_url}/review/{job.rdl_run_id}"

    try:
        publisher = InstagrapiPublisher(credentials)
        result = publisher.publish(
            video_path, caption,
            media_type=media_type,
            mentions=ig_handles or [],
            link_url=replay_url,
        )
        pr.status = PublishResult.Status.PUBLISHED
        pr.platform_post_id = result["post_id"]
        pr.platform_url = result.get("url", "")
        pr.published_at = timezone.now()
        pr.save()
        logger.info("Job #%d: published to IG via instagrapi: %s", job.id, result.get("url"))
        return result["post_id"]
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


def _add_to_event_highlight(job, story_post_id: str, credentials=None):
    """
    If the job's session's event has a highlight configured,
    add the published story to it. Creates the highlight on first use
    if it was marked as "pending".
    """
    session = getattr(job, "session", None)
    if not session:
        return

    event = session.event
    if not event.ig_highlight_pk:
        return

    if not credentials or credentials.method != "instagrapi":
        logger.warning("Job #%d: highlights require instagrapi credentials", job.id)
        return

    try:
        from .instagram import InstagramHighlightManager
        mgr = InstagramHighlightManager(credentials)

        if event.ig_highlight_pk == "pending":
            result = mgr.create_highlight(
                title=event.name[:16],
                story_media_ids=[story_post_id],
            )
            event.ig_highlight_pk = result["highlight_pk"]
            event.ig_highlight_url = result["url"]
            event.save(update_fields=["ig_highlight_pk", "ig_highlight_url"])
            logger.info("Job #%d: created highlight for event %d: %s", job.id, event.id, result["url"])
        else:
            mgr.add_to_highlight(event.ig_highlight_pk, [story_post_id])
            logger.info("Job #%d: added story to highlight %s", job.id, event.ig_highlight_pk)

    except Exception as exc:
        logger.exception("Job #%d: failed to add to highlight: %s", job.id, exc)


def _build_caption(job) -> str:
    parts = []
    organisation = resolve_organisation_for_job(job)

    if job.driver_name:
        parts.append(job.driver_name)

    if job.run_number:
        parts.append(f"Run {job.run_number}")

    stats = _extract_stats(job.run_metadata)
    if stats.get("max_speed"):
        parts.append(f"Top Speed: {stats['max_speed']:.0f} km/h")
    if stats.get("max_drift_angle"):
        parts.append(f"Max Angle: {stats['max_drift_angle']:.1f}°")

    hashtags = ["#drift", "#motorsport", "#racedatalabs", "#rdl"]
    if organisation and organisation.instagram_handle:
        tag = organisation.instagram_handle.lstrip("@")
        hashtags.append(f"#{tag}")

    parts.append("")
    parts.append(" ".join(hashtags))

    return " | ".join(p for p in parts if p) if parts else "Race Data Labs"


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


def _maybe_publish_ad(job, story_piece):
    """
    Increment the event's ad counter. When it reaches ad_frequency,
    publish the ad video as a Story and reset the counter.
    """
    session = getattr(job, "session", None)
    if not session:
        return

    event = session.event
    if not event.ads_enabled or not event.ad_video:
        return

    Event.objects.filter(id=event.id).update(
        posts_since_last_ad=models.F("posts_since_last_ad") + 1,
    )
    event.refresh_from_db(fields=["posts_since_last_ad"])

    if event.posts_since_last_ad < event.ad_frequency:
        logger.info(
            "Job #%d: ad counter %d/%d",
            job.id, event.posts_since_last_ad, event.ad_frequency,
        )
        return

    media_root = Path(settings.MEDIA_ROOT)
    ad_path = Path(event.ad_video.path)
    if not ad_path.exists():
        logger.error("Job #%d: ad video file missing: %s", job.id, ad_path)
        return

    handle = event.ad_instagram_handle
    caption = f"@{handle}" if handle else ""
    logger.info("Job #%d: publishing ad video (every %d posts), tagging @%s", job.id, event.ad_frequency, handle)

    pr = PublishResult.objects.create(
        content_piece=story_piece,
        platform=PublishResult.Platform.INSTAGRAM_STORY,
        status=PublishResult.Status.UPLOADING,
        caption=f"[AD] {caption}",
    )

    try:
        organisation = resolve_organisation_for_job(job)
        ig_creds = get_instagram_credentials(organisation)
        if ig_creds and ig_creds.method == "instagrapi":
            from .instagram import InstagrapiPublisher
            publisher = InstagrapiPublisher(ig_creds)
            result = publisher.publish(
                ad_path, caption,
                media_type="STORIES",
                mentions=[handle] if handle else [],
            )
        elif ig_creds and ig_creds.method == "graph":
            from .instagram import InstagramGraphPublisher
            publisher = InstagramGraphPublisher(ig_creds)
            result = publisher.publish(ad_path, caption, media_type="STORIES")
        else:
            logger.warning("Job #%d: no IG credentials for ad publish", job.id)
            pr.delete()
            return

        pr.status = PublishResult.Status.PUBLISHED
        pr.platform_post_id = result["post_id"]
        pr.platform_url = result.get("url", "")
        pr.published_at = timezone.now()
        pr.save()

        Event.objects.filter(id=event.id).update(posts_since_last_ad=0)
        logger.info("Job #%d: ad published, counter reset", job.id)

    except Exception as exc:
        pr.status = PublishResult.Status.FAILED
        pr.error_message = str(exc)[:2000]
        pr.save()
        logger.exception("Job #%d: ad publish failed", job.id)


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
