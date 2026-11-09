"""The "left to deliver" numbers and the recipient on My orders"""

# Standard Library
from decimal import Decimal

# Django
from django.test import override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.messages import display_name
from evebuilders.models import ContractRecord, ContractSource, Order, OrderAssignment
from evebuilders.orders import my_shares, recipient_name
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES


class LeftTestCase(ViewsTestCase):
    """A builder with 400 of an order of 1000 at 1 000 000 ISK"""

    def _source(self):
        return ContractSource.objects.create(
            corporation_id=98000001, corporation_name="Test Corp"
        )

    def _row(self):
        return my_shares(self.builder)[0]


class TestLeftToDeliver(LeftTestCase):
    """The numbers of a share"""

    def test_left_is_taken_minus_credited(self):
        share = self._take(self.builder, 400)
        OrderAssignment.objects.filter(pk=share.pk).update(credited=100)

        row = self._row()

        self.assertEqual(row["left"], 300)
        self.assertEqual(row["left_total"], Decimal("300000000.00"))

    def test_a_contract_that_waits_is_not_delivered_yet(self):
        share = self._take(self.builder, 400)
        OrderAssignment.objects.filter(pk=share.pk).update(credited=100)
        ContractRecord.objects.create(
            contract_id=1,
            order=self.order,
            assignment=share,
            issuer_character_id=1,
            quantity=150,
            state=ContractRecord.State.OUTSTANDING,
        )

        row = self._row()

        self.assertEqual(row["left"], 300)  # the 150 in the contract still count
        self.assertEqual(row["releasable"], 150)  # but only 150 can be given back


class TestRecipient(LeftTestCase):
    """Who the items are delivered to"""

    def test_a_corporate_order_goes_to_the_connected_corporation(self):
        source = self._source()

        self.assertEqual(recipient_name(self.order, source), "Test Corp")

    def test_without_a_connection_nobody_is_known(self):
        self.assertEqual(recipient_name(self.order, None), "")

    def test_a_private_order_goes_to_its_customer(self):
        Order.objects.filter(pk=self.order.pk).update(kind=Order.Kind.PRIVATE)
        self.order.refresh_from_db()

        self.assertEqual(
            recipient_name(self.order, self._source()), display_name(self.manager)
        )


@override_settings(STORAGES=TEST_STORAGES)
class TestMyOrdersPage(LeftTestCase):
    """The page"""

    def _page(self):
        self.client.force_login(self.builder)

        return self.client.get(reverse("evebuilders:my_orders"))

    def test_the_new_columns_and_the_instruction(self):
        self._source()
        self._take(self.builder, 400)

        response = self._page()

        self.assertContains(response, "Left to deliver")
        self.assertContains(response, "Total left")
        self.assertContains(response, "How to deliver")
        self.assertContains(response, 'data-copy="Test Corp"')
        self.assertContains(response, 'data-copy="400000000"')

    def test_the_discard_button_says_how_many_can_be_given_back(self):
        self._take(self.builder, 400)

        response = self._page()

        self.assertContains(response, "Discard (400)")
        self.assertNotContains(response, "Can be given back")