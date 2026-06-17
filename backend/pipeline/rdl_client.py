"""
HTTP client for the rdl-base API.

Supports two auth modes:
1. Internal API key (X-Internal-Key header) -- for same-network / edge deployments
2. Session auth (username/password login) -- for cloud servers like fd.racedatalabs.com

Sessions are cached per server configuration. Pass an Organisation to target
that org's rdl-base server; otherwise global settings are used.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_sessions: dict[str, requests.Session] = {}


@dataclass(frozen=True)
class RdlConfig:
    base_url: str
    api_url: str
    internal_api_key: str
    api_username: str
    api_password: str

    @property
    def cache_key(self) -> str:
        return self.api_url

    @classmethod
    def from_settings(cls) -> RdlConfig:
        return cls(
            base_url=settings.RDL_BASE_URL.rstrip("/"),
            api_url=settings.RDL_BASE_API_URL.rstrip("/"),
            internal_api_key=settings.RDL_INTERNAL_API_KEY,
            api_username=getattr(settings, "RDL_API_USERNAME", ""),
            api_password=getattr(settings, "RDL_API_PASSWORD", ""),
        )

    @classmethod
    def from_organisation(cls, organisation) -> RdlConfig:
        if organisation is None:
            return cls.from_settings()
        return cls(
            base_url=(organisation.rdl_base_url or settings.RDL_BASE_URL).rstrip("/"),
            api_url=(organisation.rdl_base_api_url or settings.RDL_BASE_API_URL).rstrip("/"),
            internal_api_key=organisation.rdl_internal_api_key or settings.RDL_INTERNAL_API_KEY,
            api_username=organisation.rdl_api_username or getattr(settings, "RDL_API_USERNAME", ""),
            api_password=organisation.rdl_api_password or getattr(settings, "RDL_API_PASSWORD", ""),
        )


def get_config(organisation=None) -> RdlConfig:
    if organisation is not None:
        return RdlConfig.from_organisation(organisation)
    return RdlConfig.from_settings()


def get_session(organisation=None) -> requests.Session:
    config = get_config(organisation)
    session = _sessions.get(config.cache_key)
    if session is None:
        session = requests.Session()
        session.headers["Content-Type"] = "application/json"
        if config.internal_api_key:
            session.headers["X-Internal-Key"] = config.internal_api_key
        else:
            _do_login(session, config)
        _sessions[config.cache_key] = session
    return session


def _do_login(session: requests.Session, config: RdlConfig):
    """Authenticate via rdl-base's session auth endpoint (email + password)."""
    if not config.api_username or not config.api_password:
        logger.warning(
            "No internal API key or username/password for %s; API calls may be unauthenticated",
            config.api_url,
        )
        return

    login_url = f"{config.api_url}/auth/login/"
    headers = {
        "Content-Type": "application/json",
        "Referer": config.api_url,
    }

    try:
        resp = session.post(
            login_url,
            json={"email": config.api_username, "password": config.api_password},
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 200:
            logger.info("Authenticated with rdl-base API at %s as %s", config.api_url, config.api_username)
        else:
            logger.error("rdl-base login failed (%d): %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.error("rdl-base login request failed: %s", exc)


def api_get(path: str, organisation=None, **kwargs) -> requests.Response:
    """
    GET from the rdl-base API. Re-authenticates on 401/403.
    `path` is appended to the org's API URL, e.g. "/run/42/"
    """
    config = get_config(organisation)
    session = get_session(organisation)
    url = f"{config.api_url}{path}" if path.startswith("/") else path

    resp = session.get(url, timeout=kwargs.pop("timeout", 15), **kwargs)

    if resp.status_code in (401, 403) and not config.internal_api_key:
        logger.info("Got %d, re-authenticating with rdl-base at %s", resp.status_code, config.api_url)
        _do_login(session, config)
        resp = session.get(url, timeout=15, **kwargs)

    return resp


def reset_session(organisation=None):
    """Force re-authentication on next request."""
    if organisation is None:
        _sessions.clear()
        return
    config = get_config(organisation)
    _sessions.pop(config.cache_key, None)
