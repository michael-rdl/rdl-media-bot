import logging

from django.conf import settings as django_settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from pipeline.models import ContentTemplate, Job, StreamSource
from pipeline.rdl_client import api_get

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


def test_view(request):
    """Test page: show rdl-base connection status, available servers/events, and all runs."""
    error = None
    server_info = {}
    events = []
    runs = []

    try:
        server_info = {
            "url": django_settings.RDL_BASE_URL,
            "api_url": django_settings.RDL_BASE_API_URL,
        }

        # Fetch events (try authenticated endpoint)
        try:
            resp = api_get("/event/")
            if resp.status_code == 200:
                events_data = resp.json()
                events = events_data if isinstance(events_data, list) else events_data.get("results", [])
        except Exception:
            pass

        # Fetch runs
        resp = api_get("/run/")
        if resp.status_code == 200:
            runs_data = resp.json()
            runs = runs_data if isinstance(runs_data, list) else runs_data.get("results", [])
        else:
            error = f"API returned {resp.status_code}: {resp.text[:200]}"

        server_info["status"] = "Connected"
        server_info["run_count"] = len(runs)
        server_info["event_count"] = len(events)

    except Exception as exc:
        error = str(exc)
        server_info["status"] = "Error"

    return render(request, "dashboard/test.html", {
        "server_info": server_info,
        "events": events,
        "runs": runs,
        "error": error,
    })


def settings_view(request):

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
