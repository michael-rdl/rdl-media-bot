"""Meta (Facebook) OAuth flow for connecting Instagram Business accounts."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import requests
from django.conf import settings

from pipeline.models import Organisation
from publish.instagram_credentials import save_graph_credentials

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v25.0"
OAUTH_DIALOG_URL = "https://www.facebook.com/v25.0/dialog/oauth"

INSTAGRAM_SCOPES = [
    "instagram_basic",
    "instagram_content_publish",
    "pages_show_list",
    "pages_read_engagement",
]


def meta_oauth_configured() -> bool:
    return bool(settings.META_APP_ID and settings.META_APP_SECRET)


def build_oauth_url(org_id: int, redirect_uri: str) -> str:
    params = {
        "client_id": settings.META_APP_ID,
        "redirect_uri": redirect_uri,
        "scope": ",".join(INSTAGRAM_SCOPES),
        "response_type": "code",
        "state": str(org_id),
    }
    return f"{OAUTH_DIALOG_URL}?{urlencode(params)}"


def exchange_code_for_token(code: str, redirect_uri: str) -> str:
    resp = requests.get(
        f"{GRAPH_API_BASE}/oauth/access_token",
        params={
            "client_id": settings.META_APP_ID,
            "client_secret": settings.META_APP_SECRET,
            "redirect_uri": redirect_uri,
            "code": code,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", str(data["error"])))
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No access token in OAuth response: {data}")
    return token


def exchange_for_long_lived_token(short_lived_token: str) -> str:
    resp = requests.get(
        f"{GRAPH_API_BASE}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": settings.META_APP_ID,
            "client_secret": settings.META_APP_SECRET,
            "fb_exchange_token": short_lived_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("access_token", short_lived_token)


def find_instagram_business_account(user_access_token: str) -> tuple[str, str, str]:
    """
    Find the first Facebook Page with a linked Instagram Business account.

    Returns (ig_user_id, page_access_token, ig_username).
    """
    resp = requests.get(
        f"{GRAPH_API_BASE}/me/accounts",
        params={
            "fields": "id,name,access_token,instagram_business_account{id,username}",
            "access_token": user_access_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    pages = resp.json().get("data", [])

    for page in pages:
        ig_account = page.get("instagram_business_account")
        if not ig_account:
            continue
        ig_user_id = ig_account.get("id")
        page_token = page.get("access_token")
        username = ig_account.get("username", "")
        if ig_user_id and page_token:
            logger.info(
                "Found IG business account @%s (id=%s) on page '%s'",
                username,
                ig_user_id,
                page.get("name"),
            )
            return ig_user_id, page_token, username

    raise RuntimeError(
        "No Facebook Page with a linked Instagram Business account was found. "
        "Ensure the Instagram account is a Business/Creator account linked to a Facebook Page."
    )


def connect_organisation_via_oauth(organisation: Organisation, code: str, redirect_uri: str) -> dict:
    short_token = exchange_code_for_token(code, redirect_uri)
    long_token = exchange_for_long_lived_token(short_token)
    ig_user_id, page_token, username = find_instagram_business_account(long_token)

    save_graph_credentials(
        organisation,
        user_id=ig_user_id,
        access_token=page_token,
        account_name=username,
    )

    return {
        "username": username,
        "user_id": ig_user_id,
    }
