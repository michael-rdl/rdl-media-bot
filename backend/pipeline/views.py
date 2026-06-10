import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

from .models import ContentTemplate, Job, StreamSource

logger = logging.getLogger(__name__)


def _verify_webhook_secret(request):
    secret = settings.WEBHOOK_SECRET
    if not secret:
        return True
    signature = request.headers.get("X-Webhook-Signature", "")
    expected = hmac.new(
        secret.encode(), request.body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


@csrf_exempt
@require_POST
def run_complete_webhook(request):
    if not _verify_webhook_secret(request):
        return JsonResponse({"error": "Invalid signature"}, status=403)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    run_id = payload.get("run_id")
    if not run_id:
        return JsonResponse({"error": "run_id required"}, status=400)

    stream_source = StreamSource.objects.filter(active=True).first()
    template = ContentTemplate.objects.filter(active=True).first()

    job = Job.objects.create(
        rdl_run_id=run_id,
        event_session_id=payload.get("event_session_id"),
        driver_name=payload.get("driver", ""),
        run_number=str(payload.get("run_number", "")),
        stream_source=stream_source,
        template=template,
        skip_youtube_clip=stream_source is None,
    )

    from .tasks import run_pipeline

    result = run_pipeline.delay(job.id)
    job.celery_task_id = result.id
    job.save(update_fields=["celery_task_id"])

    logger.info("Created Job #%d for run_id=%s, task=%s", job.id, run_id, result.id)

    return JsonResponse({
        "job_id": job.id,
        "status": job.status,
        "celery_task_id": result.id,
    }, status=201)


@require_GET
def job_list_api(request):
    status_filter = request.GET.get("status")
    qs = Job.objects.all()
    if status_filter:
        qs = qs.filter(status=status_filter)

    jobs = []
    for job in qs[:50]:
        jobs.append({
            "id": job.id,
            "rdl_run_id": job.rdl_run_id,
            "driver_name": job.driver_name,
            "run_number": job.run_number,
            "status": job.status,
            "created_at": job.created_at.isoformat(),
        })
    return JsonResponse({"jobs": jobs})


@require_GET
def job_detail_api(request, job_id):
    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)

    pieces = []
    for piece in job.pieces.all():
        publish_results = []
        for pr in piece.publish_results.all():
            publish_results.append({
                "platform": pr.platform,
                "status": pr.status,
                "platform_url": pr.platform_url,
                "error_message": pr.error_message,
                "published_at": pr.published_at.isoformat() if pr.published_at else None,
            })
        pieces.append({
            "id": piece.id,
            "piece_type": piece.piece_type,
            "file": piece.file.url if piece.file else None,
            "duration_seconds": piece.duration_seconds,
            "width": piece.width,
            "height": piece.height,
            "publish_results": publish_results,
        })

    return JsonResponse({
        "id": job.id,
        "rdl_run_id": job.rdl_run_id,
        "driver_name": job.driver_name,
        "run_number": job.run_number,
        "status": job.status,
        "error_message": job.error_message,
        "failed_stage": job.failed_stage,
        "skip_youtube_clip": job.skip_youtube_clip,
        "publish_as_reel": job.publish_as_reel,
        "pieces": pieces,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    })


@csrf_exempt
@require_POST
def job_retry_api(request, job_id):
    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)

    if job.status != Job.Status.FAILED:
        return JsonResponse({"error": "Only failed jobs can be retried"}, status=400)

    job.status = Job.Status.TRIGGERED
    job.error_message = ""
    job.failed_stage = ""
    job.save(update_fields=["status", "error_message", "failed_stage"])

    from .tasks import run_pipeline

    result = run_pipeline.delay(job.id)
    job.celery_task_id = result.id
    job.save(update_fields=["celery_task_id"])

    return JsonResponse({"job_id": job.id, "status": job.status})
