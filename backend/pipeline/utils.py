"""Shared helpers for resolving pipeline context from jobs and events."""

from __future__ import annotations

from pipeline.models import Event, Job, Organisation, Run


def resolve_event_for_job(job: Job) -> Event | None:
    if job.session_id:
        return job.session.event
    run = Run.objects.filter(rdl_run_id=job.rdl_run_id).select_related("event__organisation").first()
    if run:
        return run.event
    return None


def resolve_organisation_for_job(job: Job) -> Organisation | None:
    event = resolve_event_for_job(job)
    if event:
        return event.organisation
    return None
