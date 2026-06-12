import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .models import ContentTemplate, Job, Session, StreamSource

logger = logging.getLogger(__name__)

LIVE_SESSION_TIMEOUT = timedelta(hours=1)


@shared_task(bind=True, max_retries=1)
def run_pipeline(self, job_id):
    """
    Main pipeline orchestrator. Runs each stage sequentially,
    updating Job status as it progresses. On failure, marks the
    job with the failed stage and error.
    """
    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist:
        logger.error("Job %d not found", job_id)
        return

    stages = [
        (Job.Status.CAPTURING, "capture", _run_capture),
        (Job.Status.CLIPPING, "clip", _run_clip),
        (Job.Status.COMPOSING, "compose", _run_compose),
        (Job.Status.PUBLISHING, "publish", _run_publish),
    ]

    for status, stage_name, stage_fn in stages:
        job.status = status
        job.status_message = ""
        job.save(update_fields=["status", "status_message"])
        logger.info("Job #%d entering stage: %s", job_id, stage_name)

        try:
            stage_fn(job)
        except Exception as exc:
            logger.exception("Job #%d failed at stage %s", job_id, stage_name)
            job.status = Job.Status.FAILED
            job.failed_stage = stage_name
            job.error_message = str(exc)[:2000]
            job.status_message = f"Failed: {stage_name}"
            job.save(update_fields=["status", "failed_stage", "error_message", "status_message"])
            return

    job.status = Job.Status.DONE
    job.status_message = ""
    job.save(update_fields=["status", "status_message"])
    logger.info("Job #%d completed successfully", job_id)


def _run_capture(job):
    from capture.tasks import capture_visualiser
    capture_visualiser(job.id)


def _run_clip(job):
    if job.skip_youtube_clip:
        logger.info("Job #%d: skipping YouTube clip (no stream source)", job.id)
        return
    from sources.tasks import clip_youtube_stream
    clip_youtube_stream(job.id)


def _run_compose(job):
    from compose.tasks import compose_story
    compose_story(job.id)


def _run_publish(job):
    from publish.tasks import publish_content
    publish_content(job.id)


@shared_task
def poll_live_sessions():
    """
    Celery beat task: check for new runs on every live session's event.
    Creates a Job for each new run and enqueues the pipeline.
    Auto-deactivates sessions after 1 hour of no new runs.
    """
    from .rdl_client import api_get

    live_sessions = Session.objects.filter(is_live=True).select_related("event")
    if not live_sessions.exists():
        return

    polled_events = {}
    now = timezone.now()

    for session in live_sessions:
        # Auto-deactivate if no runs for 1 hour
        if session.last_run_seen_at and (now - session.last_run_seen_at) > LIVE_SESSION_TIMEOUT:
            session.is_live = False
            session.save(update_fields=["is_live"])
            logger.info(
                "Session %d (%s) auto-deactivated after 1h timeout",
                session.id, session.name,
            )
            continue

        event_id = session.event.rdl_event_id

        # Fetch runs for this event (cached per event to avoid duplicate API calls)
        if event_id not in polled_events:
            try:
                resp = api_get("/run/")
                if resp.status_code != 200:
                    logger.error("poll_live_sessions: GET /run/ returned %d", resp.status_code)
                    continue
                data = resp.json()
                all_runs = data if isinstance(data, list) else data.get("results", [])
                polled_events[event_id] = [
                    r for r in all_runs if r.get("event_id") == event_id
                ]
            except Exception as exc:
                logger.exception("poll_live_sessions: failed to fetch runs: %s", exc)
                continue

        runs = polled_events.get(event_id, [])
        if not runs:
            continue

        last_polled_id = session.last_polled_run_id or 0
        new_runs = [r for r in runs if r["id"] > last_polled_id]

        if not new_runs:
            continue

        stream_source = StreamSource.objects.filter(active=True).first()
        template = ContentTemplate.objects.filter(active=True).first()

        max_run_id = last_polled_id
        for run in new_runs:
            run_id = run["id"]
            if run_id > max_run_id:
                max_run_id = run_id

            if Job.objects.filter(rdl_run_id=run_id).exists():
                continue

            job = Job.objects.create(
                rdl_run_id=run_id,
                session=session,
                event_session_id=session.rdl_session_id,
                driver_name=run.get("description", ""),
                stream_source=stream_source,
                template=template,
                skip_youtube_clip=stream_source is None,
            )

            result = run_pipeline.delay(job.id)
            job.celery_task_id = result.id
            job.save(update_fields=["celery_task_id"])

            logger.info(
                "Live session %d: created Job #%d for run %d",
                session.id, job.id, run_id,
            )

        session.last_polled_run_id = max_run_id
        session.last_run_seen_at = now
        session.save(update_fields=["last_polled_run_id", "last_run_seen_at"])
