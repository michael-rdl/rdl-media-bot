import logging

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from pipeline.models import ContentTemplate, Job, StreamSource

logger = logging.getLogger(__name__)


def job_list(request):
    status_filter = request.GET.get("status", "")
    qs = Job.objects.all()
    if status_filter:
        qs = qs.filter(status=status_filter)

    jobs = qs[:100]
    statuses = Job.Status.choices

    return render(request, "dashboard/job_list.html", {
        "jobs": jobs,
        "statuses": statuses,
        "current_status": status_filter,
    })


def job_detail(request, job_id):
    job = get_object_or_404(Job, id=job_id)
    pieces = job.pieces.prefetch_related("publish_results").all()

    return render(request, "dashboard/job_detail.html", {
        "job": job,
        "pieces": pieces,
    })


@require_POST
def job_retry(request, job_id):
    job = get_object_or_404(Job, id=job_id)

    if job.status != Job.Status.FAILED:
        return redirect("dashboard:job-detail", job_id=job.id)

    job.status = Job.Status.TRIGGERED
    job.error_message = ""
    job.failed_stage = ""
    job.save(update_fields=["status", "error_message", "failed_stage"])

    from pipeline.tasks import run_pipeline
    result = run_pipeline.delay(job.id)
    job.celery_task_id = result.id
    job.save(update_fields=["celery_task_id"])

    return redirect("dashboard:job-detail", job_id=job.id)


def job_create(request):
    """Manual job creation form -- enter a run_id to trigger the pipeline."""
    if request.method == "POST":
        run_id = request.POST.get("run_id")
        if not run_id:
            return render(request, "dashboard/job_create.html", {"error": "Run ID is required"})

        stream_source = StreamSource.objects.filter(active=True).first()
        template = ContentTemplate.objects.filter(active=True).first()

        job = Job.objects.create(
            rdl_run_id=int(run_id),
            driver_name=request.POST.get("driver_name", ""),
            run_number=request.POST.get("run_number", ""),
            stream_source=stream_source,
            template=template,
            skip_youtube_clip=stream_source is None,
            publish_as_reel=request.POST.get("publish_as_reel") == "on",
        )

        from pipeline.tasks import run_pipeline
        result = run_pipeline.delay(job.id)
        job.celery_task_id = result.id
        job.save(update_fields=["celery_task_id"])

        return redirect("dashboard:job-detail", job_id=job.id)

    return render(request, "dashboard/job_create.html")


def stream_list(request):
    streams = StreamSource.objects.all()
    return render(request, "dashboard/stream_list.html", {"streams": streams})


@require_POST
def stream_add(request):
    label = request.POST.get("label", "").strip()
    url = request.POST.get("url", "").strip()

    if label and url:
        StreamSource.objects.create(label=label, url=url)

    return redirect("dashboard:stream-list")


@require_POST
def stream_toggle(request, pk):
    stream = get_object_or_404(StreamSource, pk=pk)
    stream.active = not stream.active
    stream.save(update_fields=["active"])
    return redirect("dashboard:stream-list")


@require_POST
def stream_delete(request, pk):
    stream = get_object_or_404(StreamSource, pk=pk)
    stream.delete()
    return redirect("dashboard:stream-list")


def template_list(request):
    templates = ContentTemplate.objects.all()
    return render(request, "dashboard/template_list.html", {"templates": templates})


def settings_view(request):
    from django.conf import settings as django_settings

    rdl_auth = "Not configured"
    if django_settings.RDL_INTERNAL_API_KEY:
        rdl_auth = "Internal API Key"
    elif django_settings.RDL_API_USERNAME:
        rdl_auth = f"Session auth ({django_settings.RDL_API_USERNAME})"

    config = {
        "RDL Base URL": django_settings.RDL_BASE_URL,
        "RDL API URL": django_settings.RDL_BASE_API_URL,
        "RDL Auth": rdl_auth,
        "Instagram Graph API": "Configured" if django_settings.INSTAGRAM_ACCESS_TOKEN else "Not configured",
        "Instagram Private API": "Configured" if django_settings.INSTAGRAM_USERNAME else "Not configured",
        "YouTube API": "Configured" if django_settings.YOUTUBE_OAUTH_TOKEN_FILE else "Not configured",
        "Webhook Secret": "Set" if django_settings.WEBHOOK_SECRET else "Not set",
    }
    return render(request, "dashboard/settings.html", {"config": config})
