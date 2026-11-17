"""Delete the orders and everything that belongs to them, the settings stay"""

# Django
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

# AA EVE Builders
from evebuilders.models import ContractRecord, Order, OrderAssignment, OrderEvent

# How many of the orders to delete the dry run lists by name
LIST_LIMIT = 50


class Command(BaseCommand):
    """Clear the orders (for example the test ones) and keep the settings"""

    help = (
        "Deletes the orders with their shares of builders, contracts and history. "
        "The settings (ESI connection, Discord, stations, levels and roles), the "
        "numbering of the orders and the events that belong to no order stay. "
        "Without --yes nothing is deleted: the command only says what it would delete."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep",
            nargs="+",
            default=[],
            metavar="NUMBER",
            help="Numbers of the orders to keep, with everything that belongs to them.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Really delete. Without it nothing is deleted.",
        )

    def handle(self, *args, **options):
        keep = sorted(set(options["keep"]))
        known = set(
            Order.objects.filter(number__in=keep).values_list("number", flat=True)
        )
        unknown = [number for number in keep if number not in known]
        if unknown:
            raise CommandError(
                f"There is no order {', '.join(unknown)}. Nothing was deleted."
            )

        orders = Order.objects.exclude(number__in=keep)
        shares = OrderAssignment.objects.filter(order__in=orders)
        contracts = ContractRecord.objects.filter(
            Q(order__isnull=True) | Q(order__in=orders)
        )
        events = OrderEvent.objects.filter(order__in=orders)

        counts = {
            "orders": orders.count(),
            "shares of builders": shares.count(),
            "contracts": contracts.count(),
            "history events of these orders": events.count(),
        }

        if not any(counts.values()):
            self.stdout.write("There is nothing to delete.")

            return

        if not options["yes"]:
            self._describe(orders, counts, keep)

            return

        with transaction.atomic():
            # In this order: the contracts and the shares protect the orders
            contracts.delete()
            shares.delete()
            orders.delete()

        summary = ", ".join(f"{count} {name}" for name, count in counts.items())
        self.stdout.write(f"Deleted: {summary}.")

    def _describe(self, orders, counts: dict, keep: list) -> None:
        """Say what a real run would delete and what stays"""

        self.stdout.write(f"Orders to delete: {counts['orders']}")
        listed = orders.select_related("eve_type").order_by("created_at")
        for order in listed[:LIST_LIMIT]:
            self.stdout.write(
                f"  {order.number}  {order.get_status_display()}  "
                f"{order.eve_type.name} x {order.quantity}"
            )
        if counts["orders"] > LIST_LIMIT:
            self.stdout.write(f"  ... and {counts['orders'] - LIST_LIMIT} more")

        for name in list(counts)[1:]:
            self.stdout.write(f"{name.capitalize()} to delete: {counts[name]}")

        if keep:
            self.stdout.write(f"Orders that stay: {', '.join(keep)}")
        self.stdout.write(
            "Stays: the settings (ESI connection, Discord, stations, levels, roles), "
            "the numbering of the orders and the events that belong to no order."
        )
        self.stdout.write("Nothing was deleted. Run it again with --yes to delete.")
