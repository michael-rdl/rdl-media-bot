"""
Reusable sync logic for pulling events and sessions from rdl-base.
Called by the sync_events management command and the dashboard sync view.
"""
import logging

from .models import Event, Session
from .rdl_client import api_get

logger = logging.getLogger(__name__)


def sync_events_from_rdl() -> dict:
    """
    Fetch all events and sessions from the rdl-base API and upsert them
    into the local Event/Session tables.

    Returns a dict with counts: {"events_created", "events_updated",
    "sessions_created", "sessions_updated", "errors"}.
    """
    counts = {
        "events_created": 0,
        "events_updated": 0,
        "sessions_created": 0,
        "sessions_updated": 0,
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
            if session_created:
                counts["sessions_created"] += 1
            else:
                counts["sessions_updated"] += 1

    logger.info(
        "Sync complete: events %d created / %d updated, sessions %d created / %d updated",
        counts["events_created"], counts["events_updated"],
        counts["sessions_created"], counts["sessions_updated"],
    )
    return counts


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


def _fetch_event_detail(event_id: int) -> dict | None:
    try:
        resp = api_get(f"/event/{event_id}/")
        if resp.status_code == 200:
            return resp.json()
        logger.error("Event %d detail: got %d", event_id, resp.status_code)
    except Exception as exc:
        logger.error("Event %d detail failed: %s", event_id, exc)
    return None
