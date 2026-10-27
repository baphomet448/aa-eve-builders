"""Take, discard and My orders views"""

# Standard Library
from datetime import timedelta
from decimal import Decimal

# Django
from django.contrib.messages import constants, get_messages
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

# EVE Universe
from eveuniverse.models import EveCategory, EveGroup, EveType

# AA EVE Builders
from evebuilders.models import ContractRecord, Order, OrderAssignment
from evebuilders.orders import create_order, my_shares, take_order
from evebuilders.tests.test_views import TEST_STORAGES, make_user


class ViewsTestCase(TestCase):
    """A base order and a middle order of 1000 pieces, a manager and two builders"""

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
        cls.other = make_user("other", "builder_access")
        cls.order = cls._order()
        cls.middle = cls._order(Order.AccessLevel.MIDDLE)

    @classmethod
    def _order(cls, access_level=Order.AccessLevel.BASE):
        return create_order(
            user=cls.manager,
            eve_type=cls.eve_type,
            quantity=1000,
            unit_price=Decimal("1000000.00"),
            due_date=timezone.localdate() + timedelta(days=7),
            access_level=access_level,
        )

    @staticmethod
    def _take_url(order):
        return reverse("evebuilders:take_order", args=[order.pk])

    @staticmethod
    def _discard_url(order):
        return reverse("evebuilders:discard", args=[order.pk])

    @staticmethod
    def _levels(response):
        return [m.level for m in get_messages(response.wsgi_request)]

    def _take(self, user, quantity, order=None):
        return take_order(user=user, order_id=(order or self.order).pk, quantity=quantity)


@override_settings(STORAGES=TEST_STORAGES)
class TestTakeView(ViewsTestCase):
    """The Take button"""

    def test_anonymous_and_users_without_access_are_sent_away(self):
        url = self._take_url(self.order)
        nobody = make_user("nobody")

        self.assertEqual(self.client.post(url, {"quantity": "10"}).status_code, 302)

        self.client.force_login(nobody)
        self.assertEqual(self.client.post(url, {"quantity": "10"}).status_code, 302)
        self.assertFalse(OrderAssignment.objects.exists())

    def test_get_is_not_allowed(self):
        self.client.force_login(self.builder)

        response = self.client.get(self._take_url(self.order))

        self.assertEqual(response.status_code, 405)

    def test_builder_takes_a_part(self):
        self.client.force_login(self.builder)

        response = self.client.post(self._take_url(self.order), {"quantity": "300"})

        self.assertRedirects(
            response, reverse("evebuilders:orders"), fetch_redirect_response=False
        )
        self.assertEqual(OrderAssignment.objects.get().taken, 300)
        self.assertEqual(self._levels(response), [constants.SUCCESS])

    def test_more_than_is_free_gives_an_error(self):
        self.client.force_login(self.builder)

        response = self.client.post(self._take_url(self.order), {"quantity": "1001"})

        self.assertEqual(self._levels(response), [constants.ERROR])
        self.assertFalse(OrderAssignment.objects.exists())

    def test_not_a_number_gives_an_error(self):
        for value in ("abc", ""):
            with self.subTest(value=value):
                client = Client()  # fresh client: no messages left over from before
                client.force_login(self.builder)

                response = client.post(self._take_url(self.order), {"quantity": value})

                self.assertEqual(self._levels(response), [constants.ERROR])

        self.assertFalse(OrderAssignment.objects.exists())

    def test_hidden_order_is_not_found(self):
        self.client.force_login(self.builder)

        response = self.client.post(self._take_url(self.middle), {"quantity": "10"})

        self.assertEqual(response.status_code, 404)
        self.assertFalse(OrderAssignment.objects.exists())

    def test_a_manager_can_take(self):
        self.client.force_login(self.manager)

        self.client.post(self._take_url(self.middle), {"quantity": "10"})

        self.assertEqual(OrderAssignment.objects.get().taken, 10)


@override_settings(STORAGES=TEST_STORAGES)
class TestDiscardView(ViewsTestCase):
    """The Discard button"""

    def test_builder_gives_back(self):
        self._take(self.builder, 400)
        self.client.force_login(self.builder)

        response = self.client.post(self._discard_url(self.order))

        self.assertRedirects(
            response, reverse("evebuilders:my_orders"), fetch_redirect_response=False
        )
        self.assertEqual(OrderAssignment.objects.get().taken, 0)
        self.assertEqual(self._levels(response), [constants.SUCCESS])

    def test_nothing_taken_gives_an_error(self):
        self.client.force_login(self.builder)

        response = self.client.post(self._discard_url(self.order))

        self.assertEqual(self._levels(response), [constants.ERROR])

    def test_unknown_order_is_not_found(self):
        self.client.force_login(self.builder)

        response = self.client.post(reverse("evebuilders:discard", args=[999999]))

        self.assertEqual(response.status_code, 404)

    def test_get_is_not_allowed(self):
        self.client.force_login(self.builder)

        response = self.client.get(self._discard_url(self.order))

        self.assertEqual(response.status_code, 405)

    def test_anonymous_is_sent_away(self):
        response = self.client.post(self._discard_url(self.order))

        self.assertEqual(response.status_code, 302)


@override_settings(STORAGES=TEST_STORAGES)
class TestMyOrdersPage(ViewsTestCase):
    """The My orders page"""

    def test_anonymous_is_sent_away(self):
        response = self.client.get(reverse("evebuilders:my_orders"))

        self.assertEqual(response.status_code, 302)

    def test_empty_page_says_so(self):
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:my_orders"))

        self.assertContains(response, "You have not taken any orders yet.")

    def test_shows_only_own_shares(self):
        other_order = self._order()
        self._take(self.builder, 300)
        self._take(self.other, 200, order=other_order)
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:my_orders"))

        self.assertContains(response, self.order.number)
        self.assertNotContains(response, other_order.number)

    def test_discard_button_is_shown_when_something_can_be_given_back(self):
        self._take(self.builder, 300)
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:my_orders"))

        self.assertContains(response, self._discard_url(self.order))

    def test_discard_button_is_hidden_when_everything_waits_in_a_contract(self):
        share = self._take(self.builder, 300)
        ContractRecord.objects.create(
            contract_id=1001,
            order=self.order,
            assignment=share,
            issuer_character_id=1,
            quantity=300,
            state=ContractRecord.State.OUTSTANDING,
        )
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:my_orders"))

        self.assertContains(response, self.order.number)
        self.assertNotContains(response, self._discard_url(self.order))

    def test_my_orders_tab_is_shown_to_builders(self):
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:orders"))

        self.assertContains(response, reverse("evebuilders:my_orders"))


@override_settings(STORAGES=TEST_STORAGES)
class TestOrderListTakeForm(ViewsTestCase):
    """The Take form in the order list"""

    def test_form_is_shown_for_free_orders_only(self):
        full = self._order()
        self._take(self.other, 1000, order=full)
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:orders"))

        self.assertContains(response, self._take_url(self.order))
        self.assertNotContains(response, self._take_url(full))

    def test_managers_get_the_form_too(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:orders"))

        self.assertContains(response, self._take_url(self.order))


class TestMyShares(ViewsTestCase):
    """my_shares"""

    def test_only_own_shares_with_something_taken(self):
        other_order = self._order()
        self._take(self.builder, 300)
        self._take(self.other, 200, order=other_order)

        rows = my_shares(self.builder)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["order"], self.order)
        self.assertEqual(rows[0]["pending"], 0)
        self.assertEqual(rows[0]["releasable"], 300)
        self.assertTrue(rows[0]["can_discard"])

    def test_pending_and_releasable_follow_the_contracts(self):
        share = self._take(self.builder, 300)
        ContractRecord.objects.create(
            contract_id=1001,
            order=self.order,
            assignment=share,
            issuer_character_id=1,
            quantity=200,
            state=ContractRecord.State.OUTSTANDING,
        )

        row = my_shares(self.builder)[0]

        self.assertEqual(row["pending"], 200)
        self.assertEqual(row["releasable"], 100)
        self.assertTrue(row["can_discard"])

    def test_shares_given_back_completely_are_not_listed(self):
        OrderAssignment.objects.create(order=self.order, builder=self.builder, taken=0)

        self.assertEqual(my_shares(self.builder), [])

    def test_giving_back_is_not_possible_after_the_first_half(self):
        self._take(self.builder, 300)
        Order.objects.filter(pk=self.order.pk).update(
            created_at=timezone.now() - timedelta(days=6),
            due_date=timezone.localdate() + timedelta(days=2),
        )

        row = my_shares(self.builder)[0]

        self.assertEqual(row["releasable"], 300)
        self.assertFalse(row["can_discard"])