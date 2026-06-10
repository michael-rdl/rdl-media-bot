import logging
import time
from pathlib import Path
from typing import Optional

import requests
from django.conf import settings

from .base import ContentPublisher

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v25.0"
POLL_INTERVAL = 5
MAX_POLL_ATTEMPTS = 60


class InstagramGraphPublisher(ContentPublisher):
    """
    Publish to Instagram using the official Graph API container workflow.
    Requires a Business account and approved Meta App.
    """

    def __init__(self):
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
    More flexible for Stories but uses unofficial API.
    """

    def __init__(self):
        self.username = settings.INSTAGRAM_USERNAME
        self.password = settings.INSTAGRAM_PASSWORD

        if not self.username or not self.password:
            raise RuntimeError("Instagram credentials not configured for instagrapi")

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
        from instagrapi import Client

        cl = Client()
        cl.login(self.username, self.password)

        if media_type == "STORIES":
            result = cl.video_upload_to_story(video_path, caption)
        elif media_type == "REELS":
            result = cl.clip_upload(video_path, caption)
        else:
            result = cl.video_upload(video_path, caption)

        return {
            "post_id": str(result.pk),
            "url": f"https://www.instagram.com/p/{result.code}/",
        }
