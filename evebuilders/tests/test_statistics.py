"""The numbers of the tab Statistics"""

# Standard Library
import itertools
from datetime import timedelta
from decimal import Decimal

# Third Party
# Alliance Auth (and external Apps)
from eveuniverse.models import EveCategory, EveGroup, EveType

# Django
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

# AA EVE Builders
from evebuilders.models import Order, OrderAssignment
from evebuilders.orders import create_order, take_order
from evebuilders.statistics import collect_statistics, ship_class
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES

_ids = itertools.count(910000)


class TestShipClass(SimpleTestCase):
    """The class of a ship by the name of its group"""

    def test_groups_belong_to_their_class(self):
        cases = {
            "Frigate": "frigates",
            "Assault Frigate": "frigates",
            "Interceptor": "frigates",
            "Tactical Destroyer": "destroyers",
            "Cruiser": "cruisers",
            "Heavy Assault Cruiser": "cruisers",
            "Strategic Cruiser": "cruisers",
            "Command Ship": "battlecruisers",
            "Attack Battlecruiser": "battlecruisers",
            "Battleship": "battleships",
            "Black Ops": "battleships",
            "Marauder": "battleships",
            "Titan": "capital",
            "Capital Industrial Ship": "capital",
            "Freighter": "capital",
            "Jump Freighter": "capital",
            "Hauler": "other",
            "Shuttle": "other",
            "A group nobody knows": "other",
        }

        for group, expected in cases.items():
            with self.subTest(group=group):
                self.assertEqual(ship_class(group), expected)


class StatisticsTestCase(ViewsTestCase):
    """Helpers to make orders of ships of a class"""

    def setUp(self):
        # Only what a test makes is counted
        Order.objects.all().delete()

    def _ship_order(self, group_name, *, category_id=6, quantity=10, price="100"):
        category, _created = EveCategory.objects.get_or_create(
            id=category_id,
            defaults={"name": f"Category {category_id}", "published": True},
        )
        group = EveGroup.objects.create(
            id=next(_ids), name=group_name, eve_category=category, published=True
        )
        eve_type = EveType.objects.create(
            id=next(_ids), name=f"{group_name} hull", eve_group=group, published=True
        )

        return create_order(
            user=self.manager,
            eve_type=eve_type,
            quantity=quantity,
            unit_price=Decimal(price),
            due_date=timezone.localdate() + timedelta(days=7),
        )

    def _deliver(self, order, quantity):
        take_order(user=self.builder, order_id=order.pk, quantity=quantity)
        OrderAssignment.objects.filter(order=order).update(credited=quantity)


class TestStatistics(StatisticsTestCase):
    """collect_statistics"""

    def test_nothing_gives_zeros(self):
        stats = collect_statistics()

        self.assertEqual(stats.total_orders, 0)
        self.assertEqual(stats.ships_built, 0)
        self.assertEqual(stats.active_orders, 0)
        self.assertEqual(stats.buyout_cost, Decimal("0"))
        self.assertEqual(sum(stats.built_by_class.values()), 0)

    def test_the_total_does_not_count_cancelled_orders(self):
        self._ship_order("Frigate")
        cancelled = self._ship_order("Frigate")
        Order.objects.filter(pk=cancelled.pk).update(status=Order.Status.CANCELLED)

        self.assertEqual(collect_statistics().total_orders, 1)

    def test_ships_built_are_counted_by_class(self):
        self._deliver(self._ship_order("Frigate"), 4)
        self._deliver(self._ship_order("Assault Frigate"), 2)
        self._deliver(self._ship_order("Battleship"), 3)
        self._deliver(self._ship_order("Titan"), 1)
        self._deliver(self._ship_order("Hauler"), 5)

        stats = collect_statistics()

        self.assertEqual(stats.ships_built, 15)
        self.assertEqual(stats.built_by_class["frigates"], 6)
        self.assertEqual(stats.built_by_class["battleships"], 3)
        self.assertEqual(stats.built_by_class["capital"], 1)
        self.assertEqual(stats.built_by_class["other"], 5)
        self.assertEqual(stats.built_by_class["cruisers"], 0)

    def test_what_is_not_a_ship_is_not_counted(self):
        self._deliver(self._ship_order("Energy Weapon", category_id=7), 5)

        self.assertEqual(collect_statistics().ships_built, 0)

    def test_a_cancelled_order_keeps_the_ships_that_were_delivered(self):
        order = self._ship_order("Cruiser")
        self._deliver(order, 3)
        Order.objects.filter(pk=order.pk).update(status=Order.Status.CANCELLED)

        self.assertEqual(collect_statistics().built_by_class["cruisers"], 3)

    def test_the_buyout_cost_counts_only_the_active_orders(self):
        active = self._ship_order("Battleship", quantity=100, price="1000")
        done = self._ship_order("Battleship", quantity=10, price="1000")
        cancelled = self._ship_order("Battleship", quantity=10, price="1000")
        Order.objects.filter(pk=done.pk).update(status=Order.Status.COMPLETED)
        Order.objects.filter(pk=cancelled.pk).update(status=Order.Status.CANCELLED)

        stats = collect_statistics()

        self.assertEqual(stats.active_orders, 1)
        self.assertEqual(stats.buyout_cost, Decimal("100000"))
        self.assertEqual(active.quantity, 100)

    def test_the_buyout_cost_goes_down_as_items_are_delivered(self):
        order = self._ship_order("Battleship", quantity=100, price="1000")

        before = collect_statistics().buyout_cost
        self._deliver(order, 50)
        after = collect_statistics().buyout_cost

        self.assertEqual(before, Decimal("100000"))
        self.assertEqual(after, Decimal("50000"))


@override_settings(STORAGES=TEST_STORAGES)
class TestStatisticsPage(StatisticsTestCase):
    """The tab"""

    def _page(self, user):
        self.client.force_login(user)

        return self.client.get(reverse("evebuilders:management_statistics"))

    def test_a_manager_sees_the_numbers(self):
        self._deliver(self._ship_order("Battleship", quantity=100, price="1000"), 50)

        response = self._page(self.manager)

        for text in (
            "General statistics",
            "Current statistics",
            "Total orders",
            "Ships built",
            "Frigates",
            "Capital ships",
            "Other ships",
            "Buyout cost of the active orders",
            "50,000 ISK",
        ):
            with self.subTest(text=text):
                self.assertContains(response, text)
        self.assertContains(response, 'data-copy="50000"')

    def test_a_builder_is_sent_away(self):
        self.assertEqual(self._page(self.builder).status_code, 302)

    def test_the_current_statistics_come_before_the_general_ones(self):
        response = self._page(self.manager)

        content = response.content.decode()
        self.assertLess(
            content.index("Current statistics"), content.index("General statistics")
        )
