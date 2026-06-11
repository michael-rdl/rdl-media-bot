"""
Reusable sync logic for pulling events, sessions, and runs from rdl-base.
Called by the sync_events management command and the dashboard sync view.
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests as _requests
from django.conf import settings
from django.utils.dateparse import parse_datetime

from .models import Event, Run, Session
from .rdl_client import api_get

logger = logging.getLogger(__name__)

RUN_DETAIL_WORKERS = 5


def sync_events_from_rdl() -> dict:
    """
    Fetch all events, sessions, and runs from the rdl-base API and upsert
    them into local tables.
    """
    global _auth_cookies
    _auth_cookies = None

    counts = {
        "events_created": 0,
        "events_updated": 0,
        "sessions_created": 0,
        "sessions_updated": 0,
        "runs_synced": 0,
        "errors": [],
    }

    events_data = _fetch_all_events()
    if not events_data:
        counts["errors"].append("No events returned from rdl-base API")
        return counts

    for raw_event in events_data:
        rdl_event_id = raw_event.get("id")
        if not rdl_event_id:
            continue

        event_name = raw_event.get("name", "")
        event_type = raw_event.get("event_type", "")

        event_obj, event_created = Event.objects.update_or_create(
            rdl_event_id=rdl_event_id,
            defaults={"name": event_name, "event_type": event_type},
        )
        if event_created:
            counts["events_created"] += 1
        else:
            counts["events_updated"] += 1

        detail = _fetch_event_detail(rdl_event_id)
        if not detail:
            counts["errors"].append(f"Could not fetch detail for event {rdl_event_id}")
            continue

        session_name_map = {}
        for raw_session in detail.get("sessions", []):
            rdl_session_id = raw_session.get("id")
            if not rdl_session_id:
                continue

            session_obj, session_created = Session.objects.update_or_create(
                rdl_session_id=rdl_session_id,
                defaults={
                    "event": event_obj,
                    "name": raw_session.get("name", ""),
                },
            )
            session_name_map[raw_session.get("name", "")] = session_obj
            if session_created:
                counts["sessions_created"] += 1
            else:
                counts["sessions_updated"] += 1

        runs_synced = _sync_runs_for_event(event_obj, session_name_map)
        counts["runs_synced"] += runs_synced

    logger.info(
        "Sync complete: events %d/%d, sessions %d/%d, runs %d",
        counts["events_created"], counts["events_updated"],
        counts["sessions_created"], counts["sessions_updated"],
        counts["runs_synced"],
    )
    return counts


def _sync_runs_for_event(event: Event, session_name_map: dict) -> int:
    """Fetch all runs for an event, get details in parallel for session mapping."""
    all_runs = _fetch_all_runs()
    event_runs = [r for r in all_runs if r.get("event_id") == event.rdl_event_id]

    if not event_runs:
        return 0

    unmatched_ids = set(
        Run.objects.filter(event=event, session__isnull=True)
        .values_list("rdl_run_id", flat=True)
    )
    matched_ids = set(
        Run.objects.filter(event=event, session__isnull=False)
        .values_list("rdl_run_id", flat=True)
    )
    # Fetch details for runs that are new or still unmatched to a session
    new_runs = [r for r in event_runs if r["id"] not in matched_ids]

    if not new_runs:
        return 0

    logger.info("Fetching details for %d runs (event %d)...", len(new_runs), event.rdl_event_id)

    run_details = {}
    with ThreadPoolExecutor(max_workers=RUN_DETAIL_WORKERS) as pool:
        future_map = {
            pool.submit(_fetch_run_detail, r["id"]): r
            for r in new_runs
        }
        for future in as_completed(future_map):
            raw = future_map[future]
            try:
                detail = future.result()
                if detail:
                    run_details[raw["id"]] = detail
            except Exception as exc:
                logger.warning("Run %d detail failed: %s", raw["id"], exc)

    synced = 0
    for raw in new_runs:
        detail = run_details.get(raw["id"], {})
        session_name = detail.get("session_name", "")
        session_obj = session_name_map.get(session_name)

        created_str = raw.get("created") or detail.get("created")
        rdl_created = parse_datetime(created_str) if created_str else None

        Run.objects.update_or_create(
            rdl_run_id=raw["id"],
            defaults={
                "event": event,
                "session": session_obj,
                "description": raw.get("description", "") or detail.get("description", ""),
                "run_type": raw.get("run_type", "") or detail.get("run_type", ""),
                "run_number": detail.get("run_number"),
                "rdl_created_at": rdl_created,
            },
        )
        synced += 1

    logger.info("Synced %d runs for event %d", synced, event.rdl_event_id)
    return synced


def _fetch_all_events() -> list[dict]:
    all_events = []
    url = "/event/"

    while url:
        try:
            resp = api_get(url)
        except Exception as exc:
            logger.error("Failed to fetch events: %s", exc)
            break

        if resp.status_code != 200:
            logger.error("GET %s returned %d: %s", url, resp.status_code, resp.text[:300])
            break

        data = resp.json()
        if isinstance(data, list):
            all_events.extend(data)
            break

        all_events.extend(data.get("results", []))
        next_url = data.get("next")
        if next_url:
            url = next_url.split("/api/v1")[-1] if "/api/v1" in next_url else next_url
        else:
            break

    return all_events


def _fetch_all_runs() -> list[dict]:
    all_runs = []
    url = "/run/"

    while url:
        try:
            resp = api_get(url)
        except Exception as exc:
            logger.error("Failed to fetch runs: %s", exc)
            break

        if resp.status_code != 200:
            logger.error("GET %s returned %d: %s", url, resp.status_code, resp.text[:300])
            break

        data = resp.json()
        if isinstance(data, list):
            all_runs.extend(data)
            break

        all_runs.extend(data.get("results", []))
        next_url = data.get("next")
        if next_url:
            url = next_url.split("/api/v1")[-1] if "/api/v1" in next_url else next_url
        else:
            break

    return all_runs


def _fetch_event_detail(event_id: int) -> dict | None:
    try:
        resp = api_get(f"/event/{event_id}/")
        if resp.status_code == 200:
            return resp.json()
        logger.error("Event %d detail: got %d", event_id, resp.status_code)
    except Exception as exc:
        logger.error("Event %d detail failed: %s", event_id, exc)
    return None


_auth_cookies = None


def _get_auth_cookies() -> dict:
    """Authenticate once and cache cookies for all threads."""
    global _auth_cookies
    if _auth_cookies is not None:
        return _auth_cookies

    _auth_cookies = {}
    api_url = settings.RDL_BASE_API_URL.rstrip("/")

    if settings.RDL_INTERNAL_API_KEY:
        _auth_cookies = {"_header": settings.RDL_INTERNAL_API_KEY}
        return _auth_cookies

    email = getattr(settings, "RDL_API_USERNAME", "")
    password = getattr(settings, "RDL_API_PASSWORD", "")
    if email and password:
        try:
            resp = _requests.post(
                f"{api_url}/auth/login/",
                json={"email": email, "password": password},
                headers={"Content-Type": "application/json", "Referer": api_url},
                timeout=15,
            )
            if resp.status_code == 200:
                _auth_cookies = dict(resp.cookies)
                logger.info("Authenticated for run detail fetching")
            else:
                logger.warning("Auth for run details failed: %d", resp.status_code)
        except Exception as exc:
            logger.warning("Auth error: %s", exc)

    return _auth_cookies


def _fetch_run_detail(run_id: int) -> dict | None:
    """Fetch a single run's detail using shared auth cookies."""
    try:
        api_url = settings.RDL_BASE_API_URL.rstrip("/")
        cookies = _get_auth_cookies()
        headers = {"Content-Type": "application/json"}
        if "_header" in cookies:
            headers["X-Internal-Key"] = cookies["_header"]
            cookies = {}

        resp = _requests.get(
            f"{api_url}/run/{run_id}/",
            cookies=cookies,
            headers=headers,
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "session_name": data.get("session_name", ""),
                "run_number": data.get("run_number"),
                "description": data.get("description", ""),
                "run_type": data.get("run_type", ""),
                "created": data.get("created"),
            }
    except Exception as exc:
        logger.debug("Run %d detail failed: %s", run_id, exc)
    return None
