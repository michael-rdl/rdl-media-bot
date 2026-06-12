import logging

from django.conf import settings as django_settings
from django.db import models
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from pipeline.models import ContentTemplate, Event, Job, Run, Session, StreamSource
from pipeline.rdl_client import api_get
from pipeline.sync import sync_events_from_rdl

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


@require_POST
def test_generate(request, run_id):
    """Trigger the pipeline for a run from the test page."""
    stream_source = StreamSource.objects.filter(active=True).first()
    template = ContentTemplate.objects.filter(active=True).first()

    # Pull run description from the API for the driver name
    driver_name = ""
    try:
        resp = api_get(f"/run/{run_id}/")
        if resp.status_code == 200:
            data = resp.json()
            driver_name = data.get("description", "")
    except Exception:
        pass

    job = Job.objects.create(
        rdl_run_id=run_id,
        driver_name=driver_name,
        stream_source=stream_source,
        template=template,
        skip_youtube_clip=stream_source is None,
    )

    from pipeline.tasks import run_pipeline
    result = run_pipeline.delay(job.id)
    job.celery_task_id = result.id
    job.save(update_fields=["celery_task_id"])

    return redirect("dashboard:job-detail", job_id=job.id)


def event_list(request):
    events = Event.objects.prefetch_related("sessions").all()
    return render(request, "dashboard/event_list.html", {"events": events})


@require_POST
def event_sync(request):
    counts = sync_events_from_rdl()
    # Store a summary message in the session for display after redirect
    msg = (
        f"Synced: {counts['events_created']} events created, "
        f"{counts['events_updated']} updated. "
        f"{counts['sessions_created']} sessions created, "
        f"{counts['sessions_updated']} updated. "
        f"{counts['runs_synced']} runs synced."
    )
    request.session["sync_message"] = msg
    return redirect("dashboard:event-list")


def event_detail(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    sessions = event.sessions.annotate(
        job_count=models.Count("jobs"),
        run_count=models.Count("runs"),
    ).all()

    sfx_slots = _build_sfx_slots(event)

    return render(request, "dashboard/event_detail.html", {
        "event": event,
        "sessions": sessions,
        "total_runs": Run.objects.filter(event=event).count(),
        "sfx_slots": sfx_slots,
    })


@require_POST
def event_update_audio(request, event_id):
    event = get_object_or_404(Event, id=event_id)

    if request.POST.get("remove"):
        if event.audio_file:
            event.audio_file.delete(save=False)
            event.audio_file = ""
            event.save(update_fields=["audio_file"])
    elif request.FILES.get("audio_file"):
        if event.audio_file:
            event.audio_file.delete(save=False)
        event.audio_file = request.FILES["audio_file"]
        event.save(update_fields=["audio_file"])

    return redirect("dashboard:event-detail", event_id=event.id)


@require_POST
def event_update_ads(request, event_id):
    event = get_object_or_404(Event, id=event_id)

    event.ads_enabled = request.POST.get("ads_enabled") == "on"
    event.ad_frequency = max(1, int(request.POST.get("ad_frequency", 10)))
    event.ad_instagram_handle = request.POST.get("ad_instagram_handle", "truedriftofficial").strip().lstrip("@")

    if request.POST.get("remove_video"):
        if event.ad_video:
            event.ad_video.delete(save=False)
            event.ad_video = ""
    elif request.FILES.get("ad_video"):
        if event.ad_video:
            event.ad_video.delete(save=False)
        event.ad_video = request.FILES["ad_video"]

    event.save(update_fields=[
        "ads_enabled", "ad_frequency", "ad_instagram_handle", "ad_video",
    ])

    return redirect("dashboard:event-detail", event_id=event.id)


SFX_SLOTS = [
    ("sfx_entry", "Entry Popup"),
    ("sfx_zone", "Zone Popup"),
    ("sfx_score_totals", "Score Totals"),
    ("sfx_stats", "Stats"),
]


def _build_sfx_slots(event):
    """Build template context for the SFX section, with fallback info."""
    slots = []
    for field, label in SFX_SLOTS:
        own_file = getattr(event, field)
        if own_file:
            slots.append({
                "field": field, "label": label,
                "file": own_file, "inherited": False,
                "inherited_from": "", "fallback_file": None,
            })
        else:
            fallback_event = (
                Event.objects.filter(**{f"{field}__gt": ""})
                .exclude(id=event.id)
                .order_by("-created_at")
                .first()
            )
            if fallback_event:
                fb_file = getattr(fallback_event, field)
                slots.append({
                    "field": field, "label": label,
                    "file": None, "inherited": True,
                    "inherited_from": fallback_event.name,
                    "fallback_file": fb_file,
                })
            else:
                slots.append({
                    "field": field, "label": label,
                    "file": None, "inherited": False,
                    "inherited_from": "", "fallback_file": None,
                })
    return slots


@require_POST
def event_update_sfx(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    updated = []

    for field, _label in SFX_SLOTS:
        if request.POST.get(f"remove_{field}"):
            f = getattr(event, field)
            if f:
                f.delete(save=False)
            setattr(event, field, "")
            updated.append(field)
        elif request.FILES.get(field):
            f = getattr(event, field)
            if f:
                f.delete(save=False)
            setattr(event, field, request.FILES[field])
            updated.append(field)

    if updated:
        event.save(update_fields=updated)

    return redirect("dashboard:event-detail", event_id=event.id)


@require_POST
def event_create_highlight(request, event_id):
    event = get_object_or_404(Event, id=event_id)

    if event.ig_highlight_pk:
        return redirect("dashboard:event-detail", event_id=event.id)

    try:
        from publish.instagram import InstagramHighlightManager
        mgr = InstagramHighlightManager()
        # Need at least one story to create a highlight -- use a placeholder
        # For now, we'll create when the first story is published
        # Just store intent; actual creation deferred to first publish
        event.ig_highlight_pk = "pending"
        event.save(update_fields=["ig_highlight_pk"])
        logger.info("Marked event %d for highlight creation on first publish", event.id)
    except Exception as exc:
        logger.exception("Failed to set up highlight for event %d", event.id)

    return redirect("dashboard:event-detail", event_id=event.id)


def session_detail(request, session_id):
    session = get_object_or_404(
        Session.objects.select_related("event"),
        id=session_id,
    )
    runs = session.runs.all()
    jobs = session.jobs.prefetch_related(
        "pieces__publish_results",
    ).all()[:100]

    job_run_ids = set(jobs.values_list("rdl_run_id", flat=True))

    return render(request, "dashboard/session_detail.html", {
        "session": session,
        "runs": runs,
        "jobs": jobs,
        "job_run_ids": job_run_ids,
    })


@require_POST
def session_toggle_live(request, session_id):
    from django.utils import timezone
    session = get_object_or_404(Session, id=session_id)
    session.is_live = not session.is_live
    if session.is_live and not session.last_run_seen_at:
        session.last_run_seen_at = timezone.now()
    session.save(update_fields=["is_live", "last_run_seen_at"])
    return redirect("dashboard:session-detail", session_id=session.id)


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
