"""
HTTP client for the rdl-base API.

Supports two auth modes:
1. Internal API key (X-Internal-Key header) -- for same-network / edge deployments
2. Session auth (username/password login) -- for cloud servers like fd.racedatalabs.com

The session is cached for the lifetime of the process and re-authenticated
automatically on 401/403 responses.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_session = None


def get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers["Content-Type"] = "application/json"

        if settings.RDL_INTERNAL_API_KEY:
            _session.headers["X-Internal-Key"] = settings.RDL_INTERNAL_API_KEY
        else:
            _do_login(_session)

    return _session


def _do_login(session: requests.Session):
    """Authenticate via rdl-base's session auth endpoint (email + password)."""
    email = getattr(settings, "RDL_API_USERNAME", "")
    password = getattr(settings, "RDL_API_PASSWORD", "")

    if not email or not password:
        logger.warning("No RDL_INTERNAL_API_KEY or RDL_API_USERNAME/PASSWORD configured; API calls will be unauthenticated")
        return

    api_url = settings.RDL_BASE_API_URL.rstrip("/")
    login_url = f"{api_url}/auth/login/"

    resp = session.post(login_url, json={
        "email": email,
        "password": password,
    }, timeout=15)

    if resp.status_code == 200:
        logger.info("Authenticated with rdl-base API as %s", email)
    else:
        logger.error("rdl-base login failed (%d): %s", resp.status_code, resp.text[:200])


def api_get(path: str, **kwargs) -> requests.Response:
    """
    GET from the rdl-base API. Re-authenticates on 401/403.
    `path` is appended to RDL_BASE_API_URL, e.g. "/run/42/"
    """
    session = get_session()
    api_url = settings.RDL_BASE_API_URL.rstrip("/")
    url = f"{api_url}{path}"

    resp = session.get(url, timeout=kwargs.pop("timeout", 15), **kwargs)

    if resp.status_code in (401, 403) and not settings.RDL_INTERNAL_API_KEY:
        logger.info("Got %d, re-authenticating with rdl-base", resp.status_code)
        _do_login(session)
        resp = session.get(url, timeout=15, **kwargs)

    return resp


def reset_session():
    """Force re-authentication on next request."""
    global _session
    _session = None
