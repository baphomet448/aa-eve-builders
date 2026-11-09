"""Colours of the levels, copy buttons and item icons"""

# Standard Library
from decimal import Decimal

# Django
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.models import ContractRecord
from evebuilders.templatetags.evebuilders_extras import plain_isk
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES

BASE_BADGE = '<span class="badge bg-success">Base</span>'
MIDDLE_BADGE = '<span class="badge bg-warning">Middle</span>'


class TestPlainIsk(SimpleTestCase):
    """The filter that gives an amount ready to paste into the game"""

    def test_whole_isk_without_separators(self):
        cases = [
            (Decimal("1000000.00"), "1000000"),
            (Decimal("1500.50"), "1501"),
            (Decimal("0.4"), "0"),
            (250, "250"),
            (100.0, "100"),
            (None, ""),
            ("", ""),
        ]

        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(plain_isk(value), expected)


@override_settings(STORAGES=TEST_STORAGES)
class TestDetailsOnThePages(ViewsTestCase):
    """The icons, the colours and the copy buttons are on the pages"""

    def _icon(self):
        return f"https://images.evetech.net/types/{self.eve_type.pk}/icon"

    def _get(self, user, name, *args):
        self.client.force_login(user)

        return self.client.get(reverse(f"evebuilders:{name}", args=args))

    def test_the_order_list(self):
        response = self._get(self.manager, "orders")

        self.assertContains(response, self._icon())
        self.assertContains(response, BASE_BADGE)
        self.assertContains(response, MIDDLE_BADGE)
        self.assertContains(response, f'data-copy="{self.order.number}"')
        self.assertContains(response, 'data-copy="1000000"')

    def test_the_script_is_on_every_page(self):
        response = self._get(self.manager, "orders")

        self.assertContains(response, "navigator.clipboard")

    def test_my_orders(self):
        self._take(self.builder, 300)

        response = self._get(self.builder, "my_orders")

        self.assertContains(response, self._icon())
        self.assertContains(response, f'data-copy="{self.order.number}"')
        self.assertContains(response, 'data-copy="1000000"')
        self.assertContains(response, 'data-copy="300000000"')

    def test_the_order_details(self):
        response = self._get(self.manager, "order_detail", self.order.pk)

        self.assertContains(response, self._icon())
        self.assertContains(response, BASE_BADGE)
        self.assertContains(response, f'data-copy="{self.order.number}"')
        self.assertContains(response, 'data-copy="1000000"')

    def test_the_levels_page(self):
        response = self._get(self.manager, "builder_levels")

        self.assertContains(response, BASE_BADGE)

    def test_the_management_page_shows_the_icon_of_a_waiting_contract(self):
        share = self._take(self.builder, 5)
        ContractRecord.objects.create(
            contract_id=1,
            order=self.order,
            assignment=share,
            issuer_character_id=1,
            quantity=5,
            state=ContractRecord.State.OUTSTANDING,
        )

        response = self._get(self.manager, "management")

        self.assertContains(response, self._icon())