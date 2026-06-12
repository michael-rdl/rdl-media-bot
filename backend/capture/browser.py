import logging
import subprocess
import time
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

VIEWPORT = {"width": 1080, "height": 1920}


def capture_replay(run_id: int, output_path: Path, duration_seconds: float) -> Path:
    """
    Capture the video-out scene. Records from page load, then trims to
    start at the white entry page and end 2s after the final "Stats"
    card fades in.

    duration_seconds is used only as a safety timeout — the actual end
    is detected via DOM events.
    """
    from playwright.sync_api import sync_playwright

    base_url = settings.RDL_BASE_URL.rstrip("/")
    replay_url = f"{base_url}/video-out/{run_id}"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rec_dir = output_path.parent / "rec"
    rec_dir.mkdir(parents=True, exist_ok=True)

    max_scene_ms = int(max(duration_seconds * 2.5, 120) * 1000)

    logger.info("Capturing run %d at %s (timeout %.0fs)", run_id, replay_url, max_scene_ms / 1000)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--headless=new"])

        context = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(rec_dir),
            record_video_size=VIEWPORT,
        )
        page = context.new_page()

        _authenticate(page, base_url)

        logger.info("Navigating to replay...")
        recording_start = time.monotonic()
        page.goto(replay_url, wait_until="domcontentloaded", timeout=60_000)

        # --- Phase 1: wait for loading modal to disappear ---
        try:
            page.wait_for_selector("#loader", timeout=30_000)
            logger.info("Loader visible, waiting for scene data...")
        except Exception:
            if "/login" in page.url:
                raise RuntimeError(f"Auth failed - redirected to {page.url}")

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
        except Exception:
            logger.warning("Loader still visible after timeout")

        page.wait_for_timeout(1000)
        trim_seconds = time.monotonic() - recording_start + 6.0
        logger.info("Scene started (trim first %.1fs), waiting for end-of-scene...", trim_seconds)

        # --- Phase 2: wait for the "Stats" card (second end-of-scene text block) ---
        try:
            page.wait_for_function(
                """() => {
                    for (const d of document.querySelectorAll('div')) {
                        if (d.childNodes.length <= 2 &&
                            d.innerText && d.innerText.trim() === 'Stats' &&
                            getComputedStyle(d).display !== 'none' &&
                            getComputedStyle(d).opacity !== '0')
                            return true;
                    }
                    return false;
                }""",
                timeout=max_scene_ms,
            )
            logger.info("'Stats' card detected — recording 2 more seconds")
        except Exception:
            logger.warning("'Stats' card not detected within timeout, stopping anyway")

        time.sleep(2)

        page.close()
        context.close()
        browser.close()

    # Find recorded video and trim off the loading portion
    video_files = list(rec_dir.glob("*.webm"))
    if not video_files:
        raise RuntimeError(f"No video produced in {rec_dir}")

    raw_video = video_files[0]
    _trim_and_convert(raw_video, output_path, trim_seconds)
    raw_video.unlink(missing_ok=True)

    for f in rec_dir.glob("*"):
        f.unlink()
    rec_dir.rmdir()

    logger.info("Saved %s (%.1f MB)", output_path, output_path.stat().st_size / 1e6)
    return output_path


def _trim_and_convert(input_path: Path, output_path: Path, trim_start: float):
    """Trim the loading portion from the start and convert to MP4."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(trim_start),
        "-i", str(input_path),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "15",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-an",
        str(output_path),
    ]
    logger.info("Trimming %.1fs from start and converting to MP4...", trim_start)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[:500]}")


def _authenticate(page, base_url):
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
