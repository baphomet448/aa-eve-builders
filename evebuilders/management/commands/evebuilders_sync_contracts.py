"""Read the corporation contracts from ESI and apply them to the orders"""

# Standard Library
from datetime import timezone

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
            f"Contracts seen: {report.seen}. Changes in this run: "
            f"newly waiting for acceptance: {report.pending}, "
            f"credited: {report.credited} ({report.credited_items} items), "
            f"closed: {report.closed}, invalid: {report.invalid}, "
            f"skipped: {report.skipped}."
        )
        if not report.changed:
            self.stdout.write("Nothing changed since the last run.")

        self.stdout.write(
            f"Now: {report.waiting_contracts} contract(s) waiting for acceptance "
            f"({report.waiting_items} items), "
            f"{report.problem_contracts} problem contract(s)."
        )

        if report.expires is None:
            until = "an unknown time"
        else:
            until = report.expires.astimezone(timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
        self.stdout.write(
            f"ESI keeps this answer until {until}. Whatever changed in the game "
            "after ESI made it (for example a contract that was just accepted) "
            "shows up only after that."
        )