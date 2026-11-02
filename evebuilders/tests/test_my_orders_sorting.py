"""The order of the My orders page and its sortable table"""

# Standard Library
from datetime import timedelta
from decimal import Decimal

# Django
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

# AA EVE Builders
from evebuilders.models import ContractRecord, Order, OrderAssignment
from evebuilders.orders import create_order, my_shares
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES


class SortingTestCase(ViewsTestCase):
    """The builder takes orders of different priority and in different states"""

    def _taken(self, priority=Order.Priority.MEDIUM):
        order = create_order(
            user=self.manager,
            eve_type=self.eve_type,
            quantity=10,
            unit_price=Decimal("100.00"),
            due_date=timezone.localdate() + timedelta(days=7),
            priority=priority,
        )
        share = self._take(self.builder, 5, order=order)

        return order, share

    def _numbers(self):
        return [row["order"].number for row in my_shares(self.builder)]


class TestMyOrdersOrder(SortingTestCase):
    """my_shares puts what is still to be delivered first"""

    def test_status_then_priority_then_newer_first(self):
        low, _share = self._taken(Order.Priority.LOW)
        high, _share = self._taken(Order.Priority.HIGH)

        done, done_share = self._taken(Order.Priority.HIGH)
        OrderAssignment.objects.filter(pk=done_share.pk).update(credited=5)

        review, review_share = self._taken(Order.Priority.MEDIUM)
        ContractRecord.objects.create(
            contract_id=1,
            order=review,
            assignment=review_share,
            issuer_character_id=1,
            quantity=5,
            state=ContractRecord.State.OUTSTANDING,
        )

        cancelled, _share = self._taken(Order.Priority.HIGH)
        Order.objects.filter(pk=cancelled.pk).update(status=Order.Status.CANCELLED)

        self.assertEqual(
            self._numbers(),
            [
                high.number,  # in progress, high
                low.number,  # in progress, low
                review.number,  # under review
                done.number,  # done
                cancelled.number,  # cancelled
            ],
        )

    def test_newer_orders_come_first_within_status_and_priority(self):
        older, _share = self._taken()
        newer, _share = self._taken()

        self.assertEqual(self._numbers(), [newer.number, older.number])

    def test_rows_have_the_ranks_the_table_sorts_by(self):
        _order, _share = self._taken(Order.Priority.HIGH)

        row = my_shares(self.builder)[0]

        self.assertEqual(row["status_rank"], 0)  # in progress
        self.assertEqual(row["priority_rank"], 0)  # high


@override_settings(STORAGES=TEST_STORAGES)
class TestMyOrdersPage(SortingTestCase):
    """The page"""

    def test_the_table_can_be_sorted_and_has_a_priority_column(self):
        self._taken()
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:my_orders"))

        self.assertContains(response, 'id="evebuilders-my-orders"')
        self.assertContains(response, 'data-sort="number"')
        self.assertContains(response, 'data-sort="text"')
        self.assertContains(response, "Priority")

    def test_rows_follow_the_default_order(self):
        low, _share = self._taken(Order.Priority.LOW)
        high, _share = self._taken(Order.Priority.HIGH)
        self.client.force_login(self.builder)

        content = self.client.get(reverse("evebuilders:my_orders")).content.decode()

        self.assertLess(content.index(high.number), content.index(low.number))

    def test_the_order_list_still_uses_the_shared_sorting(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:orders"))

        self.assertContains(response, 'id="evebuilders-orders"')
        self.assertContains(response, "th.sorted-asc")