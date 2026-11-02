"""Prices on the My orders page"""

# Standard Library
from decimal import Decimal

# Django
from django.test import override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.orders import my_shares
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES


class TestMyOrdersPrices(ViewsTestCase):
    """The unit price and the total of what is taken"""

    def test_a_share_knows_the_total_of_what_is_taken(self):
        self._take(self.builder, 300)

        row = my_shares(self.builder)[0]

        self.assertEqual(row["total"], Decimal("300000000.00"))

    @override_settings(STORAGES=TEST_STORAGES)
    def test_the_page_shows_the_unit_price_and_the_total(self):
        self._take(self.builder, 300)
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:my_orders"))

        self.assertContains(response, "Price per unit")
        self.assertContains(response, "Total price")
        self.assertContains(response, "1,000,000.00")
        self.assertContains(response, "300,000,000.00")
