from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class ContentPublisher(ABC):
    """Abstract base class for social media publishers."""

    @abstractmethod
    def publish(
        self,
        video_path: Path,
        caption: str,
        *,
        thumbnail_path: Optional[Path] = None,
        tags: Optional[list[str]] = None,
        **kwargs,
    ) -> dict:
        """
        Publish a video to the platform.

        Returns a dict with at minimum:
        - "post_id": platform-specific post identifier
        - "url": public URL of the published post (if available)
        """
        ...
