"""
Fetch all events and sessions from the rdl-base API and upsert them into
the local Event/Session tables.  Run with:

    python manage.py sync_events
"""
from django.core.management.base import BaseCommand

from pipeline.sync import sync_events_from_rdl


class Command(BaseCommand):
    help = "Pull events and sessions from fd.racedatalabs.com into the local database"

    def handle(self, **options):
        self.stdout.write("Syncing events from rdl-base...")
        counts = sync_events_from_rdl()

        for err in counts.get("errors", []):
            self.stderr.write(f"  Error: {err}")

        self.stdout.write(self.style.SUCCESS(
            f"Done. Events: {counts['events_created']} created, {counts['events_updated']} updated. "
            f"Sessions: {counts['sessions_created']} created, {counts['sessions_updated']} updated."
        ))
