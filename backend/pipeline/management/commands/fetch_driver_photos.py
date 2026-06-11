"""
Download driver portrait images from formulad.com and save them
to each Driver's `picture` ImageField.

    python manage.py fetch_driver_photos
    python manage.py fetch_driver_photos --dry-run
"""
import re
import time
import logging

import requests
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from pipeline.models import Driver

logger = logging.getLogger(__name__)

FD_BASE = "https://www.formulad.com"
SKIP_FILENAMES = {"background", "vehicle", "header", "stf-header", "banner-bg"}


class Command(BaseCommand):
    help = "Download driver photos from formulad.com into the Driver.picture field"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--overwrite", action="store_true", help="Re-download even if picture already set")

    def handle(self, **options):
        dry_run = options["dry_run"]
        overwrite = options["overwrite"]

        drivers = Driver.objects.all().order_by("last_name", "first_name")
        saved = 0
        skipped = 0
        failed = 0

        for driver in drivers:
            if driver.picture and not overwrite:
                self.stdout.write(f"  {driver}: already has photo, skipping")
                skipped += 1
                continue

            image_url, filename = self._find_portrait(driver.first_name, driver.last_name)
            if not image_url:
                self.stderr.write(f"  {driver}: no portrait found")
                failed += 1
                continue

            if dry_run:
                self.stdout.write(f"  [DRY RUN] {driver}: would download {image_url}")
                continue

            image_data = self._download(image_url)
            if not image_data:
                self.stderr.write(f"  {driver}: download failed")
                failed += 1
                continue

            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
            safe_name = f"{driver.first_name}_{driver.last_name}.{ext}".replace(" ", "_")

            driver.picture.save(safe_name, ContentFile(image_data), save=True)
            self.stdout.write(f"  {driver}: saved {safe_name} ({len(image_data) // 1024}KB)")
            saved += 1
            time.sleep(0.3)

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Saved: {saved}, Skipped: {skipped}, Failed: {failed}"
        ))

    def _slug(self, first, last):
        name = f"{first}-{last}".lower()
        name = name.replace("'", "").replace(" ", "-").replace(".", "")
        return re.sub(r"-+", "-", name)

    def _find_portrait(self, first, last):
        slug = self._slug(first, last)
        url = f"{FD_BASE}/drivers/{slug}"
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return None, None
        except Exception:
            return None, None

        matches = re.findall(r'/api/media/file/([^"\'&]+\.(?:png|jpg|jpeg|webp))', resp.text)
        portraits = []
        for m in matches:
            lower = m.lower()
            if any(skip in lower for skip in SKIP_FILENAMES):
                continue
            portraits.append(m)

        if not portraits:
            return None, None

        # Deduplicate and prefer the first unique portrait
        seen = set()
        for p in portraits:
            if p not in seen:
                seen.add(p)
                image_url = f"{FD_BASE}/api/media/file/{p}"
                return image_url, p

        return None, None

    def _download(self, url):
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200 and len(resp.content) > 1000:
                return resp.content
        except Exception:
            pass
        return None
