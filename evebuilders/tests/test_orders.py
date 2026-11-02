"""Order helper tests"""

# Standard Library
from datetime import date

# Django
from django.test import TestCase
from django.utils import timezone

# AA EVE Builders
from evebuilders.models import OrderSequence
from evebuilders.orders import next_order_number


class TestNextOrderNumber(TestCase):
    """Order numbers: N + yyyymmdd + - + counter of the day"""

    def test_format_and_first_number(self):
        self.assertEqual(next_order_number(date(2026, 10, 18)), "N20261018-1")

    def test_counter_goes_up_within_a_day(self):
        day = date(2026, 10, 18)

        numbers = [next_order_number(day) for _ in range(3)]

        self.assertEqual(numbers, ["N20261018-1", "N20261018-2", "N20261018-3"])

    def test_every_day_has_its_own_counter(self):
        self.assertEqual(next_order_number(date(2026, 10, 18)), "N20261018-1")
        self.assertEqual(next_order_number(date(2026, 10, 19)), "N20261019-1")
        self.assertEqual(next_order_number(date(2026, 10, 18)), "N20261018-2")

    def test_defaults_to_today(self):
        today = timezone.localdate()

        self.assertEqual(next_order_number(), f"N{today:%Y%m%d}-1")

    def test_counter_is_stored(self):
        day = date(2026, 10, 18)

        next_order_number(day)
        next_order_number(day)

        self.assertEqual(OrderSequence.objects.get(date=day).last_number, 2)
