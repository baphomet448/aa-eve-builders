"""What a manager may not do: ESI, Discord and deleting an order that was taken"""

# Django
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.manager_actions import can_delete_order, cancel_order
from evebuilders.models import Order, OrderAssignment
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES

User = get_user_model()

TAKEN_MESSAGE = "Only an admin can delete an order that a builder has taken."


@override_settings(STORAGES=TEST_STORAGES)
class RoleLimitsTestCase(ViewsTestCase):
    """
    self.manager is an admin. self.officer is a manager: the builder of the
    fixtures with the permission of a manager.
    """

    def setUp(self):
        self.builder.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="evebuilders", codename="manager_access"
            )
        )
        self.officer = User.objects.get(pk=self.builder.pk)

    def _get(self, user, name, *args):
        self.client.force_login(user)

        return self.client.get(reverse(name, args=args))

    def _post(self, user, name, *args):
        self.client.force_login(user)

        return self.client.post(reverse(name, args=args))

    def _fresh_order(self) -> Order:
        return Order.objects.get(pk=self.order.pk)


class TestSettingsOfAdminsOnly(RoleLimitsTestCase):
    """ESI, the catalog and Discord are for admins"""

    def test_the_esi_settings_and_discord_are_for_admins(self):
        for name in ("evebuilders:settings", "evebuilders:discord_settings"):
            with self.subTest(page=name):
                self.assertEqual(self._get(self.officer, name).status_code, 302)
                self.assertEqual(self._get(self.manager, name).status_code, 200)

    def test_the_actions_of_admins_are_closed_to_a_manager(self):
        for name in ("evebuilders:sync_catalog", "evebuilders:discord_test"):
            with self.subTest(action=name):
                response = self._post(self.officer, name)

                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith("/account/login/"))

    def test_a_manager_keeps_the_levels_and_the_stations(self):
        for name in ("evebuilders:builder_levels", "evebuilders:stations"):
            with self.subTest(page=name):
                self.assertEqual(self._get(self.officer, name).status_code, 200)

    def test_the_tabs_follow_the_role(self):
        manager_page = self._get(self.officer, "evebuilders:builder_levels")
        admin_page = self._get(self.manager, "evebuilders:builder_levels")

        for name in ("evebuilders:settings", "evebuilders:discord_settings"):
            link = f'href="{reverse(name)}"'
            with self.subTest(link=name):
                self.assertNotContains(manager_page, link)
                self.assertContains(admin_page, link)
        for name in ("evebuilders:builder_levels", "evebuilders:stations"):
            link = f'href="{reverse(name)}"'
            with self.subTest(link=name):
                self.assertContains(manager_page, link)


class TestDeletingOrders(RoleLimitsTestCase):
    """Who may delete which order"""

    def test_an_admin_deletes_any_order(self):
        self.assertTrue(can_delete_order(self.manager, self._fresh_order()))

        self._take(self.builder, 5)

        self.assertTrue(can_delete_order(self.manager, self._fresh_order()))

    def test_a_manager_deletes_an_order_only_until_somebody_takes_it(self):
        self.assertTrue(can_delete_order(self.officer, self._fresh_order()))

        self._take(self.builder, 5)
        self.assertFalse(can_delete_order(self.officer, self._fresh_order()))

        # The builder gives everything back
        OrderAssignment.objects.filter(order=self.order).update(taken=0)
        self.assertTrue(can_delete_order(self.officer, self._fresh_order()))

    def test_a_cancelled_order_cannot_be_deleted_again(self):
        Order.objects.filter(pk=self.order.pk).update(status=Order.Status.CANCELLED)

        self.assertFalse(can_delete_order(self.manager, self._fresh_order()))
        self.assertFalse(can_delete_order(self.officer, self._fresh_order()))

    def test_the_service_tells_a_manager_why_not(self):
        self._take(self.builder, 5)

        with self.assertRaises(ValidationError) as caught:
            cancel_order(actor=self.officer, order_id=self.order.pk)

        self.assertEqual(caught.exception.messages, [TAKEN_MESSAGE])
        self.assertNotEqual(self._fresh_order().status, Order.Status.CANCELLED)

    def test_the_service_lets_an_admin_delete_a_taken_order(self):
        self._take(self.builder, 5)

        cancel_order(actor=self.manager, order_id=self.order.pk)

        self.assertEqual(self._fresh_order().status, Order.Status.CANCELLED)


class TestTheOrderPage(RoleLimitsTestCase):
    """The card for deleting on the page of the order"""

    def _action(self) -> str:
        return f'action="{reverse("evebuilders:delete_order", args=[self.order.pk])}"'

    def _page(self, user):
        return self._get(user, "evebuilders:order_detail", self.order.pk)

    def test_a_manager_sees_the_form_while_nobody_has_taken_the_order(self):
        response = self._page(self.officer)

        self.assertContains(response, self._action())
        self.assertNotContains(response, TAKEN_MESSAGE)

    def test_a_manager_sees_the_reason_instead_when_the_order_was_taken(self):
        self._take(self.builder, 5)

        response = self._page(self.officer)

        self.assertNotContains(response, self._action())
        self.assertContains(response, TAKEN_MESSAGE)

    def test_an_admin_always_sees_the_form(self):
        self._take(self.builder, 5)

        self.assertContains(self._page(self.manager), self._action())

    def test_a_cancelled_order_has_neither_the_form_nor_the_note(self):
        Order.objects.filter(pk=self.order.pk).update(status=Order.Status.CANCELLED)

        response = self._page(self.officer)

        self.assertNotContains(response, self._action())
        self.assertNotContains(response, TAKEN_MESSAGE)

    def test_a_manager_cannot_delete_a_taken_order_by_a_request(self):
        self._take(self.builder, 5)

        response = self._post(self.officer, "evebuilders:delete_order", self.order.pk)

        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(self._fresh_order().status, Order.Status.CANCELLED)
