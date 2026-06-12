import logging
import subprocess
import time
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

VIEWPORT = {"width": 1080, "height": 1920}


_POLL_JS = """() => {
    const vis = (el) => {
        const s = getComputedStyle(el);
        return s.display !== 'none' && s.opacity !== '0';
    };
    const textDiv = (label) => {
        for (const d of document.querySelectorAll('div')) {
            if (d.childNodes.length <= 2 &&
                d.innerText && d.innerText.trim() === label && vis(d))
                return true;
        }
        return false;
    };
    const result = {};

    // Entry: visible divs with driver/event text (they sit directly in root)
    const root = document.getElementById('animationContainer');
    if (root) {
        for (const d of root.parentElement.querySelectorAll(':scope > div')) {
            if (d.id) continue;
            const txt = (d.innerText || '').trim();
            if (txt && txt.length > 2 && txt.length < 120 && vis(d))
                result.entry = true;
        }
    }

    // Zones: #informationLayerCar1 or #informationLayerCar2 becoming visible
    const il1 = document.getElementById('informationLayerCar1');
    const il2 = document.getElementById('informationLayerCar2');
    if ((il1 && vis(il1)) || (il2 && vis(il2)))
        result.zone = true;

    // Score Totals
    if (textDiv('Score Totals')) result.score_totals = true;

    // Stats
    if (textDiv('Stats')) result.stats = true;

    return result;
}"""


def capture_replay(
    run_id: int,
    output_path: Path,
    duration_seconds: float,
    on_progress=None,
):
    """
    Capture the video-out scene. Records from page load, trims to
    start at the white entry page and end 2s after the final "Stats"
    card fades in.

    Returns (output_path, scene_events) where scene_events is a list
    of {"type": str, "t": float} dicts with timestamps relative to the
    trimmed video start.

    duration_seconds is used only as a safety timeout.
    on_progress: optional callable(message: str) invoked at each phase.
    """
    from playwright.sync_api import sync_playwright

    def _progress(msg):
        logger.info("Run %d: %s", run_id, msg)
        if on_progress:
            on_progress(msg)

    base_url = settings.RDL_BASE_URL.rstrip("/")
    replay_url = f"{base_url}/video-out/{run_id}"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rec_dir = output_path.parent / "rec"
    rec_dir.mkdir(parents=True, exist_ok=True)

    max_scene_seconds = max(duration_seconds * 2.5, 120)

    _progress("Starting browser...")

    scene_events = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--headless=new"])

        context = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(rec_dir),
            record_video_size=VIEWPORT,
        )
        page = context.new_page()

        _progress("Authenticating...")
        _authenticate(page, base_url)

        _progress("Loading scene...")
        recording_start = time.monotonic()
        page.goto(replay_url, wait_until="domcontentloaded", timeout=60_000)

        # --- Phase 1: wait for loading modal to disappear ---
        try:
            page.wait_for_selector("#loader", timeout=30_000)
            _progress("Scene data loading...")
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
        scene_start = time.monotonic()
        _progress("Recording animation...")

        # --- Phase 2: poll DOM for scene events until Stats detected ---
        seen = set()
        zone_was_visible = False
        stats_detected = False

        while (time.monotonic() - scene_start) < max_scene_seconds:
            state = page.evaluate(_POLL_JS)

            now = time.monotonic() - scene_start

            if state.get("entry") and "entry" not in seen:
                seen.add("entry")
                scene_events.append({"type": "entry", "t": round(now, 2)})
                logger.info("Run %d: entry popup at %.1fs", run_id, now)

            zone_visible = state.get("zone", False)
            if zone_visible and not zone_was_visible:
                scene_events.append({"type": "zone", "t": round(now, 2)})
                logger.info("Run %d: zone popup at %.1fs", run_id, now)
            zone_was_visible = zone_visible

            if state.get("score_totals") and "score_totals" not in seen:
                seen.add("score_totals")
                scene_events.append({"type": "score_totals", "t": round(now, 2)})
                logger.info("Run %d: score totals at %.1fs", run_id, now)

            if state.get("stats") and "stats" not in seen:
                seen.add("stats")
                scene_events.append({"type": "stats", "t": round(now, 2)})
                logger.info("Run %d: stats card at %.1fs", run_id, now)
                _progress("End-of-scene detected, finishing up...")
                stats_detected = True
                break

            time.sleep(0.5)

        if not stats_detected:
            logger.warning("Run %d: stats not detected within timeout", run_id)
            _progress("Timeout reached, finishing up...")

        time.sleep(2)

        page.close()
        context.close()
        browser.close()

    # Find recorded video and trim off the loading portion
    video_files = list(rec_dir.glob("*.webm"))
    if not video_files:
        raise RuntimeError(f"No video produced in {rec_dir}")

    _progress("Encoding MP4...")
    raw_video = video_files[0]
    _trim_and_convert(raw_video, output_path, trim_seconds)
    raw_video.unlink(missing_ok=True)

    for f in rec_dir.glob("*"):
        f.unlink()
    rec_dir.rmdir()

    file_mb = output_path.stat().st_size / 1e6
    _progress(f"Capture complete ({file_mb:.1f} MB)")
    logger.info("Run %d: scene events: %s", run_id, scene_events)
    return output_path, scene_events


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
