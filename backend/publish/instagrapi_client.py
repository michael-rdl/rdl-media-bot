"""Shared instagrapi client with persisted session files."""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings

from publish.instagram_credentials import InstagramCredentials

logger = logging.getLogger(__name__)

SESSION_DIR = Path(settings.MEDIA_ROOT) / "ig_sessions"


def session_path_for(organisation_id: int | None) -> Path:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    name = f"org_{organisation_id}.json" if organisation_id else "global.json"
    return SESSION_DIR / name


def get_instagrapi_client(
    credentials: InstagramCredentials,
    *,
    organisation_id: int | None = None,
):
    """
    Return an authenticated instagrapi Client, reusing a saved session when
    possible. Session files live under MEDIA_ROOT/ig_sessions/.
    """
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired

    session_file = session_path_for(organisation_id)
    cl = Client()
    cl.delay_range = [1, 3]

    if session_file.exists():
        try:
            cl.load_settings(session_file)
        except Exception as exc:
            logger.warning("Could not load IG session %s: %s", session_file, exc)
            session_file.unlink(missing_ok=True)
            cl = Client()
            cl.delay_range = [1, 3]

    try:
        cl.login(credentials.username, credentials.password)
    except LoginRequired:
        session_file.unlink(missing_ok=True)
        cl = Client()
        cl.delay_range = [1, 3]
        cl.login(credentials.username, credentials.password)

    try:
        cl.dump_settings(session_file)
    except Exception as exc:
        logger.warning("Could not save IG session to %s: %s", session_file, exc)

    return cl


def clear_instagrapi_session(organisation_id: int | None = None) -> None:
    session_path_for(organisation_id).unlink(missing_ok=True)


def is_login_required_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    if "login_required" in message:
        return True
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            body = response.json()
            return body.get("message") == "login_required"
        except Exception:
            pass
    return False
