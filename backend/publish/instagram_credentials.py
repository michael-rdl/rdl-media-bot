"""Resolve and validate Instagram credentials for an organisation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests
from django.conf import settings
from django.utils import timezone

from pipeline.models import Organisation

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v25.0"


@dataclass
class InstagramCredentials:
    method: str
    user_id: str = ""
    access_token: str = ""
    username: str = ""
    password: str = ""


def get_instagram_credentials(organisation: Organisation | None) -> InstagramCredentials | None:
    """Return org-level credentials, falling back to global env settings."""
    if organisation and organisation.instagram_auth_method:
        if organisation.instagram_auth_method == Organisation.InstagramAuthMethod.GRAPH:
            if organisation.instagram_user_id and organisation.instagram_access_token:
                return InstagramCredentials(
                    method="graph",
                    user_id=organisation.instagram_user_id,
                    access_token=organisation.instagram_access_token,
                )
        elif organisation.instagram_auth_method == Organisation.InstagramAuthMethod.INSTAGRAPI:
            if organisation.instagram_username and organisation.instagram_password:
                return InstagramCredentials(
                    method="instagrapi",
                    username=organisation.instagram_username,
                    password=organisation.instagram_password,
                )

    if settings.INSTAGRAM_ACCESS_TOKEN and settings.INSTAGRAM_USER_ID:
        return InstagramCredentials(
            method="graph",
            user_id=settings.INSTAGRAM_USER_ID,
            access_token=settings.INSTAGRAM_ACCESS_TOKEN,
        )

    if settings.INSTAGRAM_USERNAME and settings.INSTAGRAM_PASSWORD:
        return InstagramCredentials(
            method="instagrapi",
            username=settings.INSTAGRAM_USERNAME,
            password=settings.INSTAGRAM_PASSWORD,
        )

    return None


def organisation_has_instagram(organisation: Organisation | None) -> bool:
    return get_instagram_credentials(organisation) is not None


def test_instagram_connection(organisation: Organisation | None = None) -> dict:
    """
    Verify credentials by fetching account profile info.
    Returns {"ok": bool, "message": str, "account": dict|None}.
    """
    creds = get_instagram_credentials(organisation)
    if not creds:
        return {
            "ok": False,
            "message": "No Instagram credentials configured for this organisation.",
            "account": None,
        }

    try:
        if creds.method == "graph":
            account = _test_graph_connection(creds)
        else:
            account = _test_instagrapi_connection(creds)
    except Exception as exc:
        logger.exception("Instagram connection test failed")
        return {"ok": False, "message": str(exc), "account": None}

    if organisation:
        organisation.instagram_account_name = account.get("username", "")
        organisation.instagram_connected_at = timezone.now()
        organisation.save(update_fields=["instagram_account_name", "instagram_connected_at"])

    handle = account.get("username", "")
    return {
        "ok": True,
        "message": f"Connected as @{handle}" if handle else "Connection successful",
        "account": account,
    }


def _test_graph_connection(creds: InstagramCredentials) -> dict:
    url = f"{GRAPH_API_BASE}/{creds.user_id}"
    params = {
        "fields": "username,name,profile_picture_url,media_count,followers_count",
        "access_token": creds.access_token,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", str(data["error"])))
    return {
        "method": "graph",
        "username": data.get("username", ""),
        "name": data.get("name", ""),
        "profile_picture_url": data.get("profile_picture_url", ""),
        "media_count": data.get("media_count"),
        "followers_count": data.get("followers_count"),
        "user_id": creds.user_id,
    }


def _test_instagrapi_connection(creds: InstagramCredentials) -> dict:
    from instagrapi import Client

    cl = Client()
    cl.login(creds.username, creds.password)
    user = cl.account_info()
    return {
        "method": "instagrapi",
        "username": user.username,
        "name": user.full_name,
        "profile_picture_url": str(user.profile_pic_url) if user.profile_pic_url else "",
        "media_count": user.media_count,
        "followers_count": user.follower_count,
        "user_id": str(user.pk),
    }


def save_graph_credentials(
    organisation: Organisation,
    *,
    user_id: str,
    access_token: str,
    account_name: str = "",
) -> None:
    organisation.instagram_auth_method = Organisation.InstagramAuthMethod.GRAPH
    organisation.instagram_user_id = user_id.strip()
    organisation.instagram_access_token = access_token.strip()
    organisation.instagram_username = ""
    organisation.instagram_password = ""
    organisation.instagram_account_name = account_name.lstrip("@")
    organisation.instagram_connected_at = timezone.now()
    organisation.save()


def save_instagrapi_credentials(
    organisation: Organisation,
    *,
    username: str,
    password: str,
) -> None:
    organisation.instagram_auth_method = Organisation.InstagramAuthMethod.INSTAGRAPI
    organisation.instagram_username = username.strip().lstrip("@")
    organisation.instagram_password = password
    organisation.instagram_user_id = ""
    organisation.instagram_access_token = ""
    organisation.instagram_account_name = ""
    organisation.instagram_connected_at = None
    organisation.save()


def clear_instagram_credentials(organisation: Organisation) -> None:
    organisation.instagram_auth_method = ""
    organisation.instagram_user_id = ""
    organisation.instagram_access_token = ""
    organisation.instagram_username = ""
    organisation.instagram_password = ""
    organisation.instagram_account_name = ""
    organisation.instagram_connected_at = None
    organisation.save()
