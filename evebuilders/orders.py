"""Order helpers"""

# Standard Library
from datetime import date

# Django
from django.db import transaction
from django.utils import timezone

# AA EVE Builders
from evebuilders.models import OrderSequence


def next_order_number(day: date | None = None) -> str:
    """
    Next order number, e.g. N20261018-1.

    The counter is kept per day in OrderSequence and read under a row lock, so
    two simultaneous requests never get the same number. Numbers are never
    reused, even after an order is deleted (the counter only goes up).

    :param day: The day the number is for, today (server time) by default
    :return: The order number
    """

    day = day or timezone.localdate()

    with transaction.atomic():
        sequence, _ = OrderSequence.objects.select_for_update().get_or_create(date=day)
        sequence.last_number += 1
        sequence.save(update_fields=["last_number"])

    return f"N{day:%Y%m%d}-{sequence.last_number}"