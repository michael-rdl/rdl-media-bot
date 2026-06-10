from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class ContentSource(ABC):
    """Abstract base class for content sources (YouTube, local files, etc.)."""

    @abstractmethod
    def fetch_clip(
        self,
        url: str,
        output_dir: Path,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> Path:
        """
        Download/extract a clip from the source.

        Returns the path to the downloaded video file.
        """
        ...

    @abstractmethod
    def extract_audio(self, video_path: Path, output_path: Path) -> Path:
        """
        Extract the audio track from a video file.

        Returns the path to the audio file.
        """
        ...
