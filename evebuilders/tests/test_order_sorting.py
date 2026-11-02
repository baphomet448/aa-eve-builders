"""The order of the order list and the calendar of the order form"""

# Standard Library
from datetime import timedelta
from decimal import Decimal

# Django
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

# AA EVE Builders
from evebuilders.models import Order
from evebuilders.orders import create_order, visible_orders
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES


class SortingTestCase(ViewsTestCase):
    """The base class has two NEW orders with MEDIUM priority (order, middle)"""

    def _make(self, priority=Order.Priority.MEDIUM, status=None):
        order = create_order(
            user=self.manager,
            eve_type=self.eve_type,
            quantity=10,
            unit_price=Decimal("100.00"),
            due_date=timezone.localdate() + timedelta(days=7),
            priority=priority,
        )
        if status:
            Order.objects.filter(pk=order.pk).update(status=status)

        return order

    def _pks(self):
        return [order.pk for order in visible_orders(self.manager)]


class TestDefaultOrdering(SortingTestCase):
    """New orders first, finished ones last, urgent first, newer first"""

    def test_status_comes_first(self):
        cancelled = self._make(Order.Priority.HIGH, Order.Status.CANCELLED)
        completed = self._make(Order.Priority.HIGH, Order.Status.COMPLETED)
        distributed = self._make(Order.Priority.HIGH, Order.Status.DISTRIBUTED)
        in_progress = self._make(Order.Priority.HIGH, Order.Status.IN_PROGRESS)
        new = self._make(Order.Priority.LOW)

        pks = self._pks()

        self.assertEqual(
            [
                pk
                for pk in pks
                if pk
                in {o.pk for o in (new, in_progress, distributed, completed, cancelled)}
            ],
            [new.pk, in_progress.pk, distributed.pk, completed.pk, cancelled.pk],
        )

    def test_urgent_orders_come_first_within_a_status(self):
        low = self._make(Order.Priority.LOW)
        high = self._make(Order.Priority.HIGH)

        pks = self._pks()

        # The base class orders are NEW with MEDIUM priority
        self.assertLess(pks.index(high.pk), pks.index(self.order.pk))
        self.assertLess(pks.index(self.order.pk), pks.index(low.pk))

    def test_newer_orders_come_first_within_status_and_priority(self):
        # "middle" was created after "order", both are NEW with MEDIUM priority
        pks = self._pks()

        self.assertLess(pks.index(self.middle.pk), pks.index(self.order.pk))

    def test_newer_means_created_later_not_a_bigger_text(self):
        orders = [self._make() for _ in range(10)]  # counters -3 ... -12

        pks = self._pks()

        # With the text "...-9" would be above "...-10"; creation order must win
        self.assertEqual(
            [pk for pk in pks if pk in {o.pk for o in orders}],
            [o.pk for o in reversed(orders)],
        )


@override_settings(STORAGES=TEST_STORAGES)
class TestOrderListPage(SortingTestCase):
    """The page shows the rows in that order and can sort by a column"""

    def test_rows_follow_the_default_order(self):
        completed = self._make(Order.Priority.HIGH, Order.Status.COMPLETED)
        new = self._make(Order.Priority.HIGH)
        self.client.force_login(self.manager)

        content = self.client.get(reverse("evebuilders:orders")).content.decode()

        self.assertLess(content.index(new.number), content.index(completed.number))

    def test_headers_can_be_clicked_to_sort(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:orders"))

        self.assertContains(response, 'id="evebuilders-orders"')
        self.assertContains(response, 'data-sort="number"')
        self.assertContains(response, 'data-sort="text"')


@override_settings(STORAGES=TEST_STORAGES)
class TestOrderFormCalendar(ViewsTestCase):
    """The date field opens its calendar on click"""

    def test_the_date_field_opens_the_calendar_on_click(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:new_order"))

        self.assertContains(response, "showPicker")
        self.assertContains(response, "id_due_date")
