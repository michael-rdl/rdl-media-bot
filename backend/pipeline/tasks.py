import logging

from celery import shared_task

from .models import Job

logger = logging.getLogger(__name__)


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
        job.save(update_fields=["status"])
        logger.info("Job #%d entering stage: %s", job_id, stage_name)

        try:
            stage_fn(job)
        except Exception as exc:
            logger.exception("Job #%d failed at stage %s", job_id, stage_name)
            job.status = Job.Status.FAILED
            job.failed_stage = stage_name
            job.error_message = str(exc)[:2000]
            job.save(update_fields=["status", "failed_stage", "error_message"])
            return

    job.status = Job.Status.DONE
    job.save(update_fields=["status"])
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
