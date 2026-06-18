import logging
import time
from pathlib import Path
from typing import Optional

import requests
from django.conf import settings

from .base import ContentPublisher
from .instagram_credentials import InstagramCredentials

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v25.0"
POLL_INTERVAL = 5
MAX_POLL_ATTEMPTS = 60


class InstagramGraphPublisher(ContentPublisher):
    """
    Publish to Instagram using the official Graph API container workflow.
    Requires a Business account and approved Meta App.
    """

    def __init__(self, credentials: InstagramCredentials | None = None):
        if credentials and credentials.method == "graph":
            self.user_id = credentials.user_id
            self.access_token = credentials.access_token
        else:
            self.user_id = settings.INSTAGRAM_USER_ID
            self.access_token = settings.INSTAGRAM_ACCESS_TOKEN

        if not self.user_id or not self.access_token:
            raise RuntimeError("Instagram Graph API credentials not configured")

    def publish(
        self,
        video_path: Path,
        caption: str,
        *,
        thumbnail_path: Optional[Path] = None,
        tags: Optional[list[str]] = None,
        media_type: str = "STORIES",
        **kwargs,
    ) -> dict:
        video_url = self._get_public_video_url(video_path)

        container_id = self._create_container(video_url, caption, media_type)
        self._wait_for_container(container_id)
        post_id = self._publish_container(container_id)

        return {
            "post_id": post_id,
            "url": f"https://www.instagram.com/stories/{self.user_id}/{post_id}/"
            if media_type == "STORIES"
            else f"https://www.instagram.com/reel/{post_id}/",
        }

    def _get_public_video_url(self, video_path: Path) -> str:
        """
        Construct a publicly accessible URL for the video file.
        The Django server must serve media files at MEDIA_SERVE_BASE_URL.
        """
        relative = str(video_path).split("/media/")[-1] if "/media/" in str(video_path) else video_path.name
        base = settings.MEDIA_SERVE_BASE_URL.rstrip("/")
        return f"{base}/{relative}"

    def _create_container(self, video_url: str, caption: str, media_type: str) -> str:
        url = f"{GRAPH_API_BASE}/{self.user_id}/media"
        data = {
            "media_type": media_type,
            "video_url": video_url,
            "caption": caption,
            "access_token": self.access_token,
        }

        resp = requests.post(url, data=data, timeout=30)
        resp.raise_for_status()
        container_id = resp.json().get("id")

        if not container_id:
            raise RuntimeError(f"No container ID in response: {resp.json()}")

        logger.info("Created IG container %s for %s", container_id, media_type)
        return container_id

    def _wait_for_container(self, container_id: str):
        url = f"{GRAPH_API_BASE}/{container_id}"
        params = {
            "fields": "status_code",
            "access_token": self.access_token,
        }

        for attempt in range(MAX_POLL_ATTEMPTS):
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            status = resp.json().get("status_code")

            if status == "FINISHED":
                logger.info("Container %s ready (attempt %d)", container_id, attempt + 1)
                return

            if status == "ERROR":
                raise RuntimeError(f"Container {container_id} errored during processing")

            logger.debug("Container %s status: %s (attempt %d)", container_id, status, attempt + 1)
            time.sleep(POLL_INTERVAL)

        raise RuntimeError(f"Container {container_id} did not finish within {MAX_POLL_ATTEMPTS * POLL_INTERVAL}s")

    def _publish_container(self, container_id: str) -> str:
        url = f"{GRAPH_API_BASE}/{self.user_id}/media_publish"
        data = {
            "creation_id": container_id,
            "access_token": self.access_token,
        }

        resp = requests.post(url, data=data, timeout=30)
        resp.raise_for_status()
        post_id = resp.json().get("id")

        if not post_id:
            raise RuntimeError(f"No post ID in publish response: {resp.json()}")

        logger.info("Published to Instagram: %s", post_id)
        return post_id


class InstagrapiPublisher(ContentPublisher):
    """
    Fallback publisher using instagrapi (private API).
    More flexible for Stories -- supports mentions, links, hashtags.
    """

    def __init__(self, credentials: InstagramCredentials | None = None, organisation_id: int | None = None):
        if credentials and credentials.method == "instagrapi":
            self.username = credentials.username
            self.password = credentials.password
            self._credentials = credentials
        else:
            self.username = settings.INSTAGRAM_USERNAME
            self.password = settings.INSTAGRAM_PASSWORD
            self._credentials = InstagramCredentials(
                method="instagrapi",
                username=self.username,
                password=self.password,
            ) if self.username and self.password else None

        if not self.username or not self.password:
            raise RuntimeError("Instagram credentials not configured for instagrapi")

        self.organisation_id = organisation_id

    def _get_client(self):
        from publish.instagrapi_client import clear_instagrapi_session, get_instagrapi_client, is_login_required_error

        try:
            return get_instagrapi_client(
                self._credentials,
                organisation_id=self.organisation_id,
            )
        except Exception as exc:
            if is_login_required_error(exc):
                clear_instagrapi_session(self.organisation_id)
                raise RuntimeError(
                    "Instagram session expired. Open the Instagram app, approve the login "
                    "if prompted, then click Test Connection on the organisation page and retry."
                ) from exc
            raise

    def publish(
        self,
        video_path: Path,
        caption: str,
        *,
        thumbnail_path: Optional[Path] = None,
        tags: Optional[list[str]] = None,
        media_type: str = "STORIES",
        mentions: Optional[list[str]] = None,
        link_url: Optional[str] = None,
        **kwargs,
    ) -> dict:
        from instagrapi.types import StoryLink, StoryMention
        from publish.instagrapi_client import clear_instagrapi_session, is_login_required_error

        cl = self._get_client()

        story_mentions = []
        if mentions:
            for i, handle in enumerate(mentions):
                try:
                    user = cl.user_info_by_username(handle)
                    story_mentions.append(StoryMention(
                        user=user,
                        x=0.5,
                        y=0.82 + (i * 0.04),
                        width=0.6,
                        height=0.04,
                    ))
                    logger.info("Added mention for @%s", handle)
                except Exception as exc:
                    logger.warning("Could not resolve @%s: %s", handle, exc)

        story_links = []
        if link_url:
            story_links.append(StoryLink(
                webUri=link_url,
                text="Watch Full Replay",
            ))

        if media_type == "STORIES":
            try:
                result = cl.video_upload_to_story(
                    video_path,
                    caption,
                    mentions=story_mentions,
                    links=story_links,
                )
            except Exception as exc:
                if is_login_required_error(exc):
                    clear_instagrapi_session(self.organisation_id)
                    raise RuntimeError(
                        "Instagram rejected the upload (login_required). Open the Instagram app, "
                        "tap 'This was me' on the security alert, click Test Connection on the "
                        "organisation page, then retry the job."
                    ) from exc
                raise
        elif media_type == "REELS":
            result = cl.clip_upload(video_path, caption)
        else:
            result = cl.video_upload(video_path, caption)

        return {
            "post_id": str(result.pk),
            "url": f"https://www.instagram.com/p/{result.code}/",
        }


class InstagramHighlightManager:
    """
    Manage Instagram Story Highlights via instagrapi (private API).
    Not wired into the publish pipeline -- call directly when needed.
    """

    def __init__(self, credentials: InstagramCredentials | None = None, organisation_id: int | None = None):
        if credentials and credentials.method == "instagrapi":
            self.username = credentials.username
            self.password = credentials.password
            self._credentials = credentials
        else:
            self.username = settings.INSTAGRAM_USERNAME
            self.password = settings.INSTAGRAM_PASSWORD
            self._credentials = InstagramCredentials(
                method="instagrapi",
                username=self.username,
                password=self.password,
            ) if self.username and self.password else None

        if not self.username or not self.password:
            raise RuntimeError("Instagram credentials not configured for highlights")

        self.organisation_id = organisation_id

    def _get_client(self):
        from publish.instagrapi_client import get_instagrapi_client

        return get_instagrapi_client(
            self._credentials,
            organisation_id=self.organisation_id,
        )

    def create_highlight(
        self,
        title: str,
        story_media_ids: list[str],
        cover_story_id: str = "",
    ) -> dict:
        """
        Create a new highlight from one or more published story media IDs.

        Returns dict with highlight_pk, highlight_id, title, and url.
        """
        cl = self._get_client()
        highlight = cl.highlight_create(
            title=title,
            story_ids=story_media_ids,
            cover_story_id=cover_story_id,
        )

        logger.info("Created IG highlight '%s' (pk=%s)", title, highlight.pk)

        return {
            "highlight_pk": str(highlight.pk),
            "highlight_id": highlight.id,
            "title": highlight.title,
            "url": f"https://www.instagram.com/stories/highlights/{highlight.pk}/",
        }

    def add_to_highlight(
        self,
        highlight_pk: str,
        story_media_ids: list[str],
    ) -> dict:
        """Add stories to an existing highlight."""
        cl = self._get_client()
        highlight = cl.highlight_add_stories(highlight_pk, story_media_ids)

        logger.info(
            "Added %d stories to highlight %s", len(story_media_ids), highlight_pk,
        )

        return {
            "highlight_pk": str(highlight.pk),
            "highlight_id": highlight.id,
            "title": highlight.title,
            "url": f"https://www.instagram.com/stories/highlights/{highlight.pk}/",
        }

    def get_highlights(self) -> list[dict]:
        """List all highlights for the authenticated account."""
        cl = self._get_client()
        user_id = cl.user_id_from_username(self.username)
        highlights = cl.user_highlights(user_id)

        return [
            {
                "highlight_pk": str(h.pk),
                "highlight_id": h.id,
                "title": h.title,
                "url": f"https://www.instagram.com/stories/highlights/{h.pk}/",
            }
            for h in highlights
        ]

    def find_or_create_highlight(
        self,
        title: str,
        story_media_ids: list[str],
    ) -> dict:
        """
        Add stories to a highlight with the given title, creating it if
        it doesn't exist yet. Useful for accumulating stories into a
        rolling highlight like "Latest Runs".
        """
        existing = self.get_highlights()
        for h in existing:
            if h["title"] == title:
                logger.info("Found existing highlight '%s' (pk=%s)", title, h["highlight_pk"])
                return self.add_to_highlight(h["highlight_pk"], story_media_ids)

        return self.create_highlight(title, story_media_ids)
