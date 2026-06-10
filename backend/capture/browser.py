import logging
import subprocess
import time
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

VIEWPORT = {"width": 1080, "height": 1920}
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
            ],
        )

        context = browser.new_context(viewport=VIEWPORT)
        page = context.new_page()

        # Step 1: Authenticate via the login API
        _authenticate(page, base_url)

        # Step 2: Navigate to the replay page
        logger.info("Navigating to replay...")
        page.goto(replay_url, wait_until="domcontentloaded", timeout=60_000)

        # Step 3: Wait for auth check to pass (the app calls /api/v1/auth/me/)
        # If auth works, it sets ready=true and renders the app with #loader
        # If auth fails, it redirects to /rdl/login
        logger.info("Waiting for app to pass auth check...")
        try:
            page.wait_for_selector("#loader", timeout=30_000)
            logger.info("App loaded (auth passed), waiting for scene data...")
        except Exception:
            # Check if we got redirected to login
            if "/login" in page.url:
                logger.error("Redirected to login page at %s", page.url)
                raise RuntimeError("Auth failed - visualiser redirected to login page")
            logger.warning("#loader not found, proceeding anyway")

        # Step 4: Wait for the scene loader to disappear
        logger.info("Waiting for scene to finish loading...")
        try:
            page.wait_for_function(
                """() => {
                    const loader = document.getElementById('loader');
                    if (!loader) return false;
                    return loader.style.display === 'none' ||
                           getComputedStyle(loader).display === 'none';
                }""",
                timeout=90_000,
            )
            logger.info("Scene loaded, ready to capture")
        except Exception:
            logger.warning("Loader still visible after timeout, capturing anyway")

        # Step 5: Let the scene settle
        page.wait_for_timeout(2000)

        # Step 6: Capture frames as screenshots
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

    # Step 7: Stitch frames into video with ffmpeg
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
    """
    Log into rdl-base via the login API. The visualiser's auth check
    calls /api/v1/auth/me/ -- the session cookie from login satisfies this.
    """
    email = getattr(settings, "RDL_API_USERNAME", "")
    password = getattr(settings, "RDL_API_PASSWORD", "")

    if not email:
        logger.warning("No auth credentials for visualiser capture")
        return

    login_url = f"{base_url}/api/v1/auth/login/"

    # Go to the base URL first so cookies are set on the right domain
    logger.info("Loading base URL for cookie domain...")
    page.goto(f"{base_url}/rdl/login", wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(2000)

    # Use the browser's fetch to call the login API (sets session cookie)
    logger.info("Logging in as %s...", email)
    result = page.evaluate(
        """async ([url, email, password]) => {
            try {
                const resp = await fetch(url, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({email, password}),
                    credentials: 'include',
                });
                const text = await resp.text();
                return {status: resp.status, ok: resp.ok, body: text.substring(0, 200)};
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

    # Verify auth works by checking /api/v1/auth/me/
    me_result = page.evaluate(
        """async (url) => {
            try {
                const resp = await fetch(url, {credentials: 'include'});
                return {status: resp.status, ok: resp.ok};
            } catch (e) {
                return {status: 0, error: e.message};
            }
        }""",
        f"{base_url}/api/v1/auth/me/",
    )
    logger.info("Auth verify /me/: %s", me_result)
