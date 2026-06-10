"""
Fetch all drivers from the rdl-base API and upsert them into the local
Driver table.  Run with:

    python manage.py sync_drivers          # normal sync
    python manage.py sync_drivers --dry-run  # preview without saving
"""
import logging

from django.core.management.base import BaseCommand

from pipeline.models import Driver
from pipeline.rdl_client import api_get

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Pull drivers from fd.racedatalabs.com and populate the local Driver table"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be synced without writing to the database",
        )

    def handle(self, **options):
        dry_run = options["dry_run"]

        drivers_data = self._fetch_all_drivers()
        if not drivers_data:
            self.stderr.write("No drivers returned from rdl-base API.")
            return

        self.stdout.write(f"Fetched {len(drivers_data)} driver(s) from rdl-base\n")

        created = 0
        updated = 0

        for raw in drivers_data:
            rdl_id = raw.get("id")
            if not rdl_id:
                continue

            detail = self._fetch_driver_detail(rdl_id)
            if detail is None:
                continue

            first_name, last_name = self._parse_name(
                detail.get("first_name", ""),
                detail.get("last_name", ""),
                detail.get("name", ""),
            )

            instagram = self._extract_handle(detail.get("instagram_url", "") or detail.get("instagram", ""))

            fields = {
                "first_name": first_name,
                "last_name": last_name,
                "car_number": str(detail.get("car_number", "") or detail.get("number", "") or ""),
                "instagram": instagram,
                "country": detail.get("country", "") or detail.get("nationality", "") or "",
                "email": detail.get("email", "") or "",
            }

            if dry_run:
                self.stdout.write(f"  [DRY RUN] #{rdl_id}: {first_name} {last_name} | car={fields['car_number']} | ig=@{instagram} | {fields['country']}")
                self.stdout.write(f"    Raw keys: {list(detail.keys())}")
                continue

            driver, was_created = Driver.objects.update_or_create(
                car_number=fields["car_number"],
                first_name=fields["first_name"],
                last_name=fields["last_name"],
                defaults=fields,
            )

            if was_created:
                created += 1
                self.stdout.write(f"  Created: {driver}")
            else:
                updated += 1
                self.stdout.write(f"  Updated: {driver}")

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f"\nDone. Created {created}, updated {updated}."
            ))

    def _fetch_all_drivers(self):
        """GET /driver/ — handles DRF pagination."""
        all_drivers = []
        url = "/driver/"

        while url:
            resp = api_get(url)
            if resp.status_code != 200:
                self.stderr.write(f"GET {url} returned {resp.status_code}: {resp.text[:300]}")
                break
            data = resp.json()
            if isinstance(data, list):
                all_drivers.extend(data)
                break
            all_drivers.extend(data.get("results", []))
            next_url = data.get("next")
            if next_url:
                url = next_url.split("/api/v1")[-1] if "/api/v1" in next_url else next_url
            else:
                break

        return all_drivers

    def _fetch_driver_detail(self, driver_id):
        """GET /driver/<id>/ for full detail."""
        try:
            resp = api_get(f"/driver/{driver_id}/")
            if resp.status_code == 200:
                return resp.json()
            self.stderr.write(f"  Driver {driver_id}: got {resp.status_code}")
        except Exception as exc:
            self.stderr.write(f"  Driver {driver_id}: {exc}")
        return None

    @staticmethod
    def _parse_name(first, last, full_name):
        if first or last:
            return first.strip(), last.strip()
        if full_name:
            parts = full_name.strip().split(None, 1)
            return parts[0], parts[1] if len(parts) > 1 else ""
        return "", ""

    @staticmethod
    def _extract_handle(value):
        if not value:
            return ""
        handle = value.rstrip("/").split("/")[-1]
        return handle.lstrip("@")
