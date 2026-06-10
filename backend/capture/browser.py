import logging
import subprocess
import time
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

VIEWPORT = {"width": 1080, "height": 1920}
SCENE_LOAD_TIMEOUT_MS = 60_000
LOADER_GONE_TIMEOUT_MS = 60_000
TARGET_FPS = 30


def capture_replay(run_id: int, output_path: Path, duration_seconds: float) -> Path:
    """
    Capture the visualiser replay as a smooth video by taking rapid
    screenshots and stitching them with ffmpeg.
    """
    from playwright.sync_api import sync_playwright

    base_url = settings.RDL_BASE_URL.rstrip("/")
    replay_url = f"{base_url}/review/{run_id}"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    frames_dir = output_path.parent / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Capturing replay for run %d at %s (%.1fs)", run_id, replay_url, duration_seconds)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-software-rasterizer",
            ],
        )

        context = browser.new_context(viewport=VIEWPORT)
        page = context.new_page()

        _authenticate(page, base_url)

        logger.info("Navigating to replay...")
        page.goto(replay_url, wait_until="domcontentloaded", timeout=60_000)

        # Wait for canvas to appear
        try:
            page.wait_for_selector("canvas", timeout=SCENE_LOAD_TIMEOUT_MS)
            logger.info("Canvas found")
        except Exception:
            logger.warning("Canvas not found within timeout")

        # Wait for the loading modal to disappear
        logger.info("Waiting for loader to finish...")
        try:
            page.wait_for_function(
                """() => {
                    const loader = document.getElementById('loader');
                    if (!loader) return true;
                    return loader.style.display === 'none' || 
                           getComputedStyle(loader).display === 'none';
                }""",
                timeout=LOADER_GONE_TIMEOUT_MS,
            )
            logger.info("Loader gone, scene is ready")
        except Exception:
            logger.warning("Loader didn't disappear within timeout, proceeding anyway")

        # Extra time for scene to settle and start animating
        page.wait_for_timeout(2000)

        # Capture frames as screenshots
        frame_interval = 1.0 / TARGET_FPS
        total_frames = int(duration_seconds * TARGET_FPS)
        logger.info("Capturing %d frames at %d fps...", total_frames, TARGET_FPS)

        for i in range(total_frames):
            frame_path = frames_dir / f"frame_{i:06d}.png"
            page.screenshot(path=str(frame_path))
            time.sleep(frame_interval)

        logger.info("All frames captured")

        page.close()
        context.close()
        browser.close()

    # Stitch frames into video with ffmpeg
    _stitch_frames(frames_dir, output_path, TARGET_FPS)

    # Clean up frames
    for f in frames_dir.glob("*.png"):
        f.unlink()
    frames_dir.rmdir()

    logger.info("Capture saved to %s", output_path)
    return output_path


def _stitch_frames(frames_dir: Path, output_path: Path, fps: int):
    """Stitch PNG frames into an MP4 video using ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%06d.png"),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        str(output_path),
    ]
    logger.info("Stitching %d fps video...", fps)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg stitch failed: {result.stderr[:500]}")


def _authenticate(page, base_url):
    """Log into rdl-base via the API so the browser session has auth cookies."""
    email = getattr(settings, "RDL_API_USERNAME", "")
    password = getattr(settings, "RDL_API_PASSWORD", "")

    if not email:
        logger.warning("No auth credentials for visualiser capture")
        return

    login_url = f"{base_url}/api/v1/auth/login/"
    logger.info("Authenticating browser session...")

    page.goto(base_url, wait_until="domcontentloaded", timeout=30_000)
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
