"""To whom the items of an order are delivered, on the list of orders and on its card"""

# Django
from django.template import Context, Template
from django.test import override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.messages import display_name
from evebuilders.models import ContractSource, Order
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES, make_user

TAG = "{% load evebuilders_extras %}{% order_recipient order as who %}{{ who }}"


@override_settings(STORAGES=TEST_STORAGES)
class RecipientTestCase(ViewsTestCase):
    """self.manager is an admin, self.rc_plain a builder who is nothing else"""

    def setUp(self):
        self.rc_plain = make_user("plain", "builder_access")

    @staticmethod
    def rc_connect(name: str = "Test Corp") -> None:
        """The corporation of the ESI connection (the table has a single row)"""

        ContractSource(corporation_id=98000001, corporation_name=name).save()

    def rc_list(self, user):
        self.client.force_login(user)

        return self.client.get(reverse("evebuilders:orders"))

    def rc_card(self, user):
        self.client.force_login(user)

        return self.client.get(
            reverse("evebuilders:order_detail", args=[self.order.pk])
        )


class TestTheTag(RecipientTestCase):
    """The tag that gives the name"""

    @staticmethod
    def rc_render(order) -> str:
        return Template(TAG).render(Context({"order": order}))

    def test_a_corporate_order_goes_to_the_corporation_of_the_connection(self):
        self.rc_connect()

        self.assertEqual(self.rc_render(self.order), "Test Corp")

    def test_without_a_connection_the_name_is_empty(self):
        self.assertEqual(ContractSource.objects.count(), 0)

        self.assertEqual(self.rc_render(self.order), "")

    def test_a_private_order_goes_to_its_customer(self):
        Order.objects.filter(pk=self.order.pk).update(
            kind=Order.Kind.PRIVATE, created_by=self.manager
        )
        order = Order.objects.get(pk=self.order.pk)

        self.assertEqual(self.rc_render(order), display_name(self.manager))


class TestRecipientOnTheList(RecipientTestCase):
    """The column Destination of the corporate orders"""

    def test_a_builder_sees_to_whom_to_deliver(self):
        self.rc_connect()

        response = self.rc_list(self.rc_plain)

        self.assertContains(response, "Deliver to: Test Corp")

    def test_a_manager_sees_it_too(self):
        self.rc_connect()

        self.assertContains(self.rc_list(self.manager), "Deliver to: Test Corp")

    def test_it_stands_under_the_station(self):
        self.rc_connect()
        Order.objects.filter(pk=self.order.pk).update(destination="Jita 4-4")

        content = self.rc_list(self.manager).content.decode()

        station = content.index('<td class="text-end">Jita 4-4')
        recipient = content.index("Deliver to: Test Corp", station)
        self.assertLess(station, recipient)
        self.assertLess(recipient - station, 200)

    def test_without_a_connection_nothing_is_shown(self):
        response = self.rc_list(self.rc_plain)

        self.assertNotContains(response, "Deliver to")


class TestRecipientOnTheCard(RecipientTestCase):
    """The field Destination of the order card"""

    def test_the_card_says_to_whom_to_deliver(self):
        self.rc_connect()

        response = self.rc_card(self.manager)

        self.assertContains(response, "Deliver to")
        self.assertContains(response, "<strong>Test Corp</strong>")

    def test_the_name_can_be_copied(self):
        self.rc_connect()

        response = self.rc_card(self.manager)

        self.assertContains(response, 'data-copy="Test Corp"')

    def test_it_stands_under_the_station(self):
        self.rc_connect()
        Order.objects.filter(pk=self.order.pk).update(destination="Jita 4-4")

        content = self.rc_card(self.manager).content.decode()

        self.assertLess(
            content.index("<dd>Jita 4-4"), content.index("<strong>Test Corp</strong>")
        )

    def test_without_a_connection_nothing_is_shown(self):
        response = self.rc_card(self.manager)

        self.assertNotContains(response, "Deliver to")
