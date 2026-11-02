"""Start the item catalog sync from the command line"""

# Django
from django.core.management.base import BaseCommand, CommandError

# AA EVE Builders
from evebuilders.catalog import SyncResult, start_catalog_sync

MESSAGES = {
    SyncResult.STARTED: (
        "Catalog sync started. The Celery worker does the loading, "
        "this can take a while."
    ),
    SyncResult.TOO_SOON: "A sync was started recently, not starting another one.",
    SyncResult.ESI_OFFLINE: "ESI appears to be offline, try again later.",
    SyncResult.NOTHING_TO_LOAD: (
        "No categories or groups are configured, nothing to load."
    ),
    SyncResult.FAILED: "Could not start the sync, see the log for details.",
}


class Command(BaseCommand):
    """Management command: evebuilders_sync_catalog"""

    help = (
        "Loads the configured EVE categories and groups into the item catalog "
        "(EVEBUILDERS_CATALOG_CATEGORY_IDS and EVEBUILDERS_CATALOG_GROUP_IDS)."
    )

    def handle(self, *args, **options):
        result = start_catalog_sync()
        text = MESSAGES[result]

        if result in (SyncResult.ESI_OFFLINE, SyncResult.FAILED):
            raise CommandError(text)

        if result is SyncResult.STARTED:
            self.stdout.write(self.style.SUCCESS(text))
        else:
            self.stdout.write(self.style.WARNING(text))
