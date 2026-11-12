"""The card of an order: the order of the lines and the price"""

# Django
from django.test import override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES


@override_settings(STORAGES=TEST_STORAGES)
class TestOrderCard(ViewsTestCase):
    """The first card of the order page"""

    def setUp(self):
        self._take(self.builder, 400)
        self.client.force_login(self.manager)
        content = self.client.get(
            reverse("evebuilders:order_detail", args=[self.order.pk])
        ).content.decode()
        self.card = content.split('id="evebuilders-order-card"')[1].split(
            'id="evebuilders-order-builders"'
        )[0]

    def test_the_lines_are_in_the_agreed_order(self):
        labels = (
            "Status",
            "Access level",
            "Item",
            "Price per unit",
            "Priority",
            "Due date",
            "Quantity",
        )

        positions = [self.card.index(f">{label}</dt>") for label in labels]

        self.assertEqual(positions, sorted(positions))

    def test_the_price_has_isk_after_the_number_and_copies_the_number(self):
        self.assertIn("1,000,000 ISK", self.card)
        self.assertIn('data-copy="1000000"', self.card)

    def test_the_quantity_is_written_line_by_line(self):
        quantity = self.card.split(">Quantity</dt>")[1]

        lines = [
            "Available: 1,000",
            "Taken: 400",
            "Ready: 0",
            "On review: 0",
            "Free: 600",
        ]
        for line in lines:
            with self.subTest(line=line):
                self.assertIn(line, quantity)
        self.assertEqual(quantity.count("<li>"), 5)

    def test_status_priority_and_level_are_badges(self):
        self.assertIn('<span class="badge bg-success">Base</span>', self.card)
        self.assertGreaterEqual(self.card.count('class="badge'), 3)
