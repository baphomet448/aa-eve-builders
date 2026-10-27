"""Read the corporation contracts from ESI and apply them to the orders"""

# Django
from django.core.management.base import BaseCommand, CommandError

# AA EVE Builders
from evebuilders.sync import sync_contracts


class Command(BaseCommand):
    """Management command: evebuilders_sync_contracts"""

    help = (
        "Reads the contracts of the connected corporation from ESI and applies "
        "them to the orders (waiting, credited, invalid, closed)."
    )

    def handle(self, *args, **options):
        report = sync_contracts()

        if report.error:
            raise CommandError(report.error)

        self.stdout.write(
            f"Contracts seen: {report.seen}, waiting for acceptance: {report.pending}, "
            f"credited: {report.credited} ({report.credited_items} items), "
            f"closed: {report.closed}, invalid: {report.invalid}, "
            f"skipped: {report.skipped}"
        )
        self.stdout.write(f"ESI keeps this answer until {report.expires}")