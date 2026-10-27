"""Order list tests"""

# Standard Library
from datetime import timedelta
from decimal import Decimal

# Django
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

# EVE Universe
from eveuniverse.models import EveCategory, EveGroup, EveType

# AA EVE Builders
from evebuilders.models import BuilderProfile, Order, OrderAssignment
from evebuilders.orders import create_order, visible_orders
from evebuilders.tests.test_views import TEST_STORAGES, make_user


class OrderListTestCase(TestCase):
    """One order for each access level, a manager and a builder"""

    @classmethod
    def setUpTestData(cls) -> None:
        category = EveCategory.objects.create(id=6, name="Ship", published=True)
        group = EveGroup.objects.create(
            id=25, name="Frigate", eve_category=category, published=True
        )
        cls.eve_type = EveType.objects.create(
            id=597, name="Punisher", eve_group=group, published=True
        )
        cls.manager = make_user("manager", "manage_access")
        cls.builder = make_user("builder", "builder_access")
        cls.base = cls._order(Order.AccessLevel.BASE)
        cls.middle = cls._order(Order.AccessLevel.MIDDLE)
        cls.senior = cls._order(Order.AccessLevel.SENIOR)

    @classmethod
    def _order(cls, access_level):
        return create_order(
            user=cls.manager,
            eve_type=cls.eve_type,
            quantity=1000,
            unit_price=Decimal("1000000.00"),
            due_date=timezone.localdate() + timedelta(days=7),
            access_level=access_level,
        )

    @staticmethod
    def _pks(user):
        return {order.pk for order in visible_orders(user)}


class TestVisibleOrders(OrderListTestCase):
    """visible_orders"""

    def test_builder_sees_only_base_orders_by_default(self):
        self.assertEqual(self._pks(self.builder), {self.base.pk})

    def test_builder_level_unlocks_orders(self):
        profile = BuilderProfile.objects.create(
            user=self.builder, level=Order.AccessLevel.MIDDLE
        )
        self.assertEqual(self._pks(self.builder), {self.base.pk, self.middle.pk})

        profile.level = Order.AccessLevel.SENIOR
        profile.save()
        self.assertEqual(
            self._pks(self.builder), {self.base.pk, self.middle.pk, self.senior.pk}
        )

    def test_manager_sees_every_order(self):
        self.assertEqual(
            self._pks(self.manager), {self.base.pk, self.middle.pk, self.senior.pk}
        )

    def test_closed_orders_are_hidden_from_builders_only(self):
        BuilderProfile.objects.create(user=self.builder, level=Order.AccessLevel.SENIOR)
        Order.objects.filter(pk=self.base.pk).update(status=Order.Status.COMPLETED)
        Order.objects.filter(pk=self.middle.pk).update(status=Order.Status.CANCELLED)

        self.assertEqual(self._pks(self.builder), {self.senior.pk})
        self.assertEqual(
            self._pks(self.manager), {self.base.pk, self.middle.pk, self.senior.pk}
        )

    def test_private_orders_are_not_listed(self):
        Order.objects.filter(pk=self.base.pk).update(kind=Order.Kind.PRIVATE)

        self.assertNotIn(self.base.pk, self._pks(self.manager))

    def test_taken_free_and_ready_are_summed_over_the_shares(self):
        other = make_user("builder2", "builder_access")
        OrderAssignment.objects.create(
            order=self.base, builder=self.builder, taken=300, credited=100
        )
        OrderAssignment.objects.create(
            order=self.base, builder=other, taken=200, credited=50
        )

        order = visible_orders(self.manager).get(pk=self.base.pk)

        self.assertEqual(order.taken, 500)
        self.assertEqual(order.credited, 150)
        self.assertEqual(order.free, 500)

    def test_order_without_shares_has_nothing_taken(self):
        order = visible_orders(self.manager).get(pk=self.base.pk)

        self.assertEqual(order.taken, 0)
        self.assertEqual(order.credited, 0)
        self.assertEqual(order.free, 1000)


@override_settings(STORAGES=TEST_STORAGES)
class TestOrderListPage(OrderListTestCase):
    """The order list page"""

    def test_anonymous_and_users_without_access_are_sent_away(self):
        url = reverse("evebuilders:orders")
        nobody = make_user("nobody")

        self.assertEqual(self.client.get(url).status_code, 302)

        self.client.force_login(nobody)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_builder_sees_only_what_he_may(self):
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:orders"))

        self.assertContains(response, self.base.number)
        self.assertNotContains(response, self.middle.number)
        self.assertNotContains(response, self.senior.number)

    def test_manager_sees_everything_and_the_level_column(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:orders"))

        for order in (self.base, self.middle, self.senior):
            self.assertContains(response, order.number)
        self.assertContains(response, "Access level")

    def test_builder_does_not_see_the_level_column(self):
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:orders"))

        self.assertNotContains(response, "Access level")

    def test_empty_list_says_so(self):
        Order.objects.all().delete()
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:orders"))

        self.assertContains(response, "No orders to show.")

    def test_index_leads_to_the_order_list(self):
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:index"))

        self.assertRedirects(
            response, reverse("evebuilders:orders"), fetch_redirect_response=False
        )

    def test_tabs(self):
        orders_url = reverse("evebuilders:orders")
        new_order_url = reverse("evebuilders:new_order")
        settings_url = reverse("evebuilders:settings")

        self.client.force_login(self.builder)
        builder_page = self.client.get(orders_url)
        self.client.force_login(self.manager)
        manager_page = self.client.get(orders_url)

        self.assertContains(builder_page, orders_url)
        self.assertNotContains(builder_page, new_order_url)
        self.assertNotContains(builder_page, settings_url)
        for url in (orders_url, new_order_url, settings_url):
            self.assertContains(manager_page, url)