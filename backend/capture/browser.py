import logging
import subprocess
import time
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

VIEWPORT = {"width": 1080, "height": 1920}
TARGET_FPS = 10


def capture_replay(run_id: int, output_path: Path, duration_seconds: float) -> Path:
    """
    Capture the visualiser replay by screenshotting at a steady rate
    and stitching into a video. Single context -- no reload needed.
    """
    from playwright.sync_api import sync_playwright

    base_url = settings.RDL_BASE_URL.rstrip("/")
    replay_url = f"{base_url}/review/{run_id}"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    frames_dir = output_path.parent / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Capturing run %d (%.1fs) at %d fps", run_id, duration_seconds, TARGET_FPS)

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

        _authenticate(page, base_url)

        page.goto(replay_url, wait_until="domcontentloaded", timeout=60_000)

        _wait_for_scene_ready(page)

        # Capture frames -- measure actual screenshot time to maintain pace
        total_frames = int(duration_seconds * TARGET_FPS)
        frame_interval = 1.0 / TARGET_FPS
        logger.info("Capturing %d frames...", total_frames)

        for i in range(total_frames):
            t0 = time.monotonic()
            page.screenshot(path=str(frames_dir / f"f_{i:06d}.png"))
            elapsed = time.monotonic() - t0
            remaining = frame_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)

        logger.info("Frames captured, stitching video...")
        page.close()
        context.close()
        browser.close()

    _stitch_frames(frames_dir, output_path)

    for f in frames_dir.glob("*.png"):
        f.unlink()
    frames_dir.rmdir()

    logger.info("Saved %s (%.1f MB)", output_path, output_path.stat().st_size / 1e6)
    return output_path


def _wait_for_scene_ready(page):
    """Wait for auth check, data load, and 3D scene to be ready."""
    try:
        page.wait_for_selector("#loader", timeout=30_000)
        logger.info("App loaded, waiting for scene...")
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
        logger.info("Scene ready")
    except Exception:
        logger.warning("Loader still visible after timeout")

    page.wait_for_timeout(2000)


def _stitch_frames(frames_dir: Path, output_path: Path):
    """Stitch frames into a smooth MP4, interpolating up to 30fps."""
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(TARGET_FPS),
        "-i", str(frames_dir / "f_%06d.png"),
        "-vf", f"minterpolate=fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir,setpts=N/30/TB",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        # Fallback without interpolation
        logger.warning("Interpolation failed, stitching without it")
        cmd2 = [
            "ffmpeg", "-y",
            "-framerate", str(TARGET_FPS),
            "-i", str(frames_dir / "f_%06d.png"),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            str(output_path),
        ]
        result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=300)
        if result2.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result2.stderr[:500]}")


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
