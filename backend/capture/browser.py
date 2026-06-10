import logging
import time
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_VIEWPORT = {"width": 1920, "height": 1080}
SCENE_LOAD_SELECTOR = "canvas"
SCENE_LOAD_TIMEOUT_MS = 30_000
PLAYBACK_POLL_INTERVAL = 1.0


def capture_replay(run_id: int, output_path: Path, duration_seconds: float) -> Path:
    """
    Launch a headless Chromium browser, navigate to the rdl-base visualiser
    replay page for the given run, and record the viewport as an MP4.

    Returns the path to the recorded video file.
    """
    from playwright.sync_api import sync_playwright

    base_url = settings.RDL_BASE_URL.rstrip("/")
    replay_url = f"{base_url}/review/{run_id}"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Capturing replay for run %d at %s (%.1fs)", run_id, replay_url, duration_seconds)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
            ],
        )

        context = browser.new_context(
            viewport=DEFAULT_VIEWPORT,
            record_video_dir=str(output_path.parent),
            record_video_size=DEFAULT_VIEWPORT,
        )

        page = context.new_page()

        page.goto(replay_url, wait_until="networkidle")

        try:
            page.wait_for_selector(SCENE_LOAD_SELECTOR, timeout=SCENE_LOAD_TIMEOUT_MS)
            logger.info("Canvas element found, scene is loading")
        except Exception:
            logger.warning("Canvas selector not found within timeout, proceeding anyway")

        # Allow the Three.js scene to fully initialize and start playback
        page.wait_for_timeout(3000)

        record_time = duration_seconds + 2.0
        logger.info("Recording for %.1f seconds", record_time)
        time.sleep(record_time)

        page.close()
        context.close()
        browser.close()

    video_files = list(output_path.parent.glob("*.webm"))
    if not video_files:
        raise RuntimeError(f"No video file produced by Playwright in {output_path.parent}")

    source_video = video_files[0]

    if output_path.suffix == ".mp4":
        _convert_webm_to_mp4(source_video, output_path)
        source_video.unlink(missing_ok=True)
    else:
        source_video.rename(output_path)

    logger.info("Capture saved to %s", output_path)
    return output_path


def _convert_webm_to_mp4(input_path: Path, output_path: Path):
    """Convert Playwright's WebM output to MP4 using ffmpeg."""
    import subprocess

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {result.stderr[:500]}")
