"""Prices in whole ISK"""

# Standard Library
from decimal import Decimal

# Django
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders import reasons
from evebuilders.forms import OrderForm
from evebuilders.reasons import reason_text
from evebuilders.templatetags.evebuilders_extras import isk
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES


class TestIskFilter(SimpleTestCase):
    """The filter that shows prices"""

    def test_whole_isk_with_separators(self):
        cases = [
            (Decimal("1000000.00"), "1,000,000"),
            (Decimal("1500.50"), "1,501"),
            (Decimal("0.4"), "0"),
            (250, "250"),
            (None, ""),
            ("", ""),
        ]

        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(isk(value), expected)


class TestPriceField(TestCase):
    """The order form takes whole ISK only"""

    @staticmethod
    def _errors(price):
        return OrderForm({"unit_price": price}).errors

    def test_whole_prices_are_fine(self):
        for price in ("100", "100.00", "1000000"):
            with self.subTest(price=price):
                self.assertNotIn("unit_price", self._errors(price))

    def test_cents_are_refused(self):
        errors = self._errors("100.50")

        self.assertIn("unit_price", errors)
        self.assertIn("whole number", errors["unit_price"][0])

    def test_the_input_steps_by_one(self):
        self.assertIn('step="1"', str(OrderForm()["unit_price"]))


class TestReasonWithoutCents(SimpleTestCase):
    """The expected price in a reason"""

    def test_cents_of_the_stored_value_are_not_shown(self):
        text = reason_text(reasons.WRONG_PRICE, {"expected": "500.00", "quantity": 5})

        self.assertEqual(text, "The price must be 500 ISK for 5 items.")

    def test_a_missing_value_does_not_crash(self):
        self.assertTrue(reason_text(reasons.WRONG_PRICE, {}))


@override_settings(STORAGES=TEST_STORAGES)
class TestPagesShowWholeIsk(ViewsTestCase):
    """The pages"""

    def _get(self, user, name, *args):
        self.client.force_login(user)

        return self.client.get(reverse(f"evebuilders:{name}", args=args))

    def test_the_order_list(self):
        response = self._get(self.manager, "orders")

        self.assertContains(response, "1,000,000")
        self.assertNotContains(response, "1,000,000.00")

    def test_my_orders(self):
        self._take(self.builder, 300)

        response = self._get(self.builder, "my_orders")

        self.assertContains(response, "300,000,000")
        self.assertNotContains(response, "300,000,000.00")

    def test_the_order_details(self):
        response = self._get(self.manager, "order_detail", self.order.pk)

        self.assertContains(response, "1,000,000")
        self.assertNotContains(response, "1,000,000.00")