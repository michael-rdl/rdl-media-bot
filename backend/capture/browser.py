import logging
import time
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_VIEWPORT = {"width": 1920, "height": 1080}
SCENE_LOAD_SELECTOR = "canvas"
SCENE_LOAD_TIMEOUT_MS = 60_000


def capture_replay(run_id: int, output_path: Path, duration_seconds: float) -> Path:
    """
    Launch a headless Chromium browser, authenticate with rdl-base,
    navigate to the visualiser replay page, wait for it to fully load,
    then start a fresh recording of just the replay.
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

        # Phase 1: authenticate and load the scene (no recording yet)
        setup_context = browser.new_context(viewport=DEFAULT_VIEWPORT)
        page = setup_context.new_page()

        _authenticate(page, base_url)

        logger.info("Navigating to replay and waiting for scene to load...")
        page.goto(replay_url, wait_until="networkidle")

        try:
            page.wait_for_selector(SCENE_LOAD_SELECTOR, timeout=SCENE_LOAD_TIMEOUT_MS)
            logger.info("Canvas found, waiting for scene to initialize...")
        except Exception:
            logger.warning("Canvas not found within timeout, proceeding anyway")

        page.wait_for_timeout(5000)

        # Grab cookies so we can transfer auth to the recording context
        cookies = setup_context.cookies()
        setup_context.close()

        # Phase 2: fresh context with recording enabled, already authenticated
        record_context = browser.new_context(
            viewport=DEFAULT_VIEWPORT,
            record_video_dir=str(output_path.parent),
            record_video_size=DEFAULT_VIEWPORT,
        )
        record_context.add_cookies(cookies)

        record_page = record_context.new_page()

        logger.info("Starting recording...")
        record_page.goto(replay_url, wait_until="networkidle")

        try:
            record_page.wait_for_selector(SCENE_LOAD_SELECTOR, timeout=SCENE_LOAD_TIMEOUT_MS)
        except Exception:
            pass

        # Wait for the scene to start rendering
        record_page.wait_for_timeout(3000)

        record_time = duration_seconds + 2.0
        logger.info("Recording for %.1f seconds", record_time)
        time.sleep(record_time)

        record_page.close()
        record_context.close()
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


def _authenticate(page, base_url):
    """Log into rdl-base via the API so the browser session has auth cookies."""
    email = getattr(settings, "RDL_API_USERNAME", "")
    password = getattr(settings, "RDL_API_PASSWORD", "")
    api_key = getattr(settings, "RDL_INTERNAL_API_KEY", "")

    if not email and not api_key:
        logger.warning("No auth credentials for visualiser capture")
        return

    if api_key:
        return

    login_url = f"{base_url}/api/v1/auth/login/"
    logger.info("Authenticating browser session...")

    page.goto(base_url, wait_until="domcontentloaded")
    page.wait_for_timeout(1000)

    result = page.evaluate(
        """async ([url, email, password]) => {
            try {
                const resp = await fetch(url, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({email, password}),
                    credentials: 'include',
                });
                return {status: resp.status, ok: resp.ok};
            } catch (e) {
                return {status: 0, error: e.message};
            }
        }""",
        [login_url, email, password],
    )

    if result.get("ok"):
        logger.info("Browser authenticated successfully")
    else:
        logger.error("Browser login failed: %s", result)


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
