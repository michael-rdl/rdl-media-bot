import logging
from pathlib import Path
from typing import Optional

from django.conf import settings

from .base import ContentPublisher

logger = logging.getLogger(__name__)


class YouTubePublisher(ContentPublisher):
    """
    Upload videos to YouTube using the Data API v3.
    Supports both Shorts (vertical, <60s) and regular uploads.
    """

    def publish(
        self,
        video_path: Path,
        caption: str,
        *,
        thumbnail_path: Optional[Path] = None,
        tags: Optional[list[str]] = None,
        title: str = "",
        description: str = "",
        is_short: bool = True,
        privacy: str = "public",
        **kwargs,
    ) -> dict:
        service = self._get_service()

        body = {
            "snippet": {
                "title": title or caption[:100],
                "description": description or caption,
                "tags": tags or [],
                "categoryId": "17",  # Sports
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        if is_short:
            body["snippet"]["title"] = f"#Shorts {body['snippet']['title']}"

        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            resumable=True,
        )

        request = service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            _, response = request.next_chunk()

        video_id = response["id"]
        url = f"https://www.youtube.com/watch?v={video_id}"

        if is_short:
            url = f"https://www.youtube.com/shorts/{video_id}"

        logger.info("Uploaded to YouTube: %s", url)

        if thumbnail_path and thumbnail_path.exists():
            try:
                service.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(str(thumbnail_path)),
                ).execute()
            except Exception:
                logger.warning("Failed to set thumbnail for %s", video_id)

        return {"post_id": video_id, "url": url}

    def _get_service(self):
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_file = settings.YOUTUBE_OAUTH_TOKEN_FILE
        if not token_file:
            raise RuntimeError("YouTube OAuth token file not configured")

        creds = Credentials.from_authorized_user_file(token_file)
        return build("youtube", "v3", credentials=creds)
