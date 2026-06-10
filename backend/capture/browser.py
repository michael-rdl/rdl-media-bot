import logging
import subprocess
import time
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

VIEWPORT = {"width": 1080, "height": 1920}


def capture_replay(run_id: int, output_path: Path, duration_seconds: float) -> Path:
    """
    Capture the visualiser replay using Playwright's native video recording.
    Two-phase approach: load everything first, then record clean.
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

        # === Phase 1: Auth + preload (no recording) ===
        setup_ctx = browser.new_context(viewport=VIEWPORT)
        page = setup_ctx.new_page()

        _authenticate(page, base_url)

        logger.info("Preloading replay page...")
        page.goto(replay_url, wait_until="domcontentloaded", timeout=60_000)

        _wait_for_scene_ready(page)

        cookies = setup_ctx.cookies()
        setup_ctx.close()
        logger.info("Preload complete, got %d cookies", len(cookies))

        # === Phase 2: Record with fresh context ===
        rec_dir = output_path.parent / "rec"
        rec_dir.mkdir(parents=True, exist_ok=True)

        rec_ctx = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(rec_dir),
            record_video_size=VIEWPORT,
        )
        rec_ctx.add_cookies(cookies)
        rec_page = rec_ctx.new_page()

        logger.info("Starting recording context...")
        rec_page.goto(replay_url, wait_until="domcontentloaded", timeout=60_000)

        _wait_for_scene_ready(rec_page)

        record_time = duration_seconds + 2.0
        logger.info("Recording for %.1f seconds...", record_time)
        time.sleep(record_time)

        rec_page.close()
        rec_ctx.close()
        browser.close()

    # Find and convert the recorded video
    video_files = list(rec_dir.glob("*.webm"))
    if not video_files:
        raise RuntimeError(f"No video file produced in {rec_dir}")

    source_video = video_files[0]
    _convert_to_mp4(source_video, output_path)
    source_video.unlink(missing_ok=True)

    for f in rec_dir.glob("*"):
        f.unlink()
    rec_dir.rmdir()

    logger.info("Capture saved to %s (%.1f MB)", output_path, output_path.stat().st_size / 1e6)
    return output_path


def _wait_for_scene_ready(page):
    """Wait for the visualiser to pass auth, load data, and be ready to animate."""
    # Wait for #loader to appear (means React app rendered, auth passed)
    try:
        page.wait_for_selector("#loader", timeout=30_000)
        logger.info("App rendered, waiting for scene data to load...")
    except Exception:
        if "/login" in page.url:
            raise RuntimeError(f"Auth failed - redirected to {page.url}")
        logger.warning("#loader not found, proceeding")

    # Wait for #loader to disappear (scene data loaded, 3D ready)
    try:
        page.wait_for_function(
            """() => {
                const el = document.getElementById('loader');
                if (!el) return false;
                return el.style.display === 'none' ||
                       getComputedStyle(el).display === 'none';
            }""",
            timeout=90_000,
        )
        logger.info("Scene ready")
    except Exception:
        logger.warning("Loader still visible after timeout")

    page.wait_for_timeout(2000)


def _convert_to_mp4(input_path: Path, output_path: Path):
    """Convert Playwright's WebM to MP4."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-an",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[:500]}")


def _authenticate(page, base_url):
    """Log in via the rdl-base login API from the browser."""
    email = getattr(settings, "RDL_API_USERNAME", "")
    password = getattr(settings, "RDL_API_PASSWORD", "")

    if not email:
        return

    logger.info("Authenticating as %s...", email)
    page.goto(f"{base_url}/rdl/login", wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(2000)

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
        [f"{base_url}/api/v1/auth/login/", email, password],
    )

    if result.get("ok"):
        logger.info("Authenticated")
    else:
        logger.error("Login failed: %s", result)
