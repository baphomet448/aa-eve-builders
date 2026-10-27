"""Take order tests"""

# Standard Library
from datetime import timedelta
from decimal import Decimal

# Django
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

# EVE Universe
from eveuniverse.models import EveCategory, EveGroup, EveType

# AA EVE Builders
from evebuilders.models import BuilderProfile, Order, OrderAssignment, OrderEvent
from evebuilders.orders import create_order, recalculate_status, take_order
from evebuilders.tests.test_views import make_user


class TakeOrderTestCase(TestCase):
    """An order of 1000 pieces, a manager and two builders"""

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

    def _refresh(self, order=None):
        order = order or self.order
        order.refresh_from_db()

        return order


class TestTakeOrder(TakeOrderTestCase):
    """take_order"""

    def test_taking_creates_a_share_and_starts_the_order(self):
        share = take_order(user=self.builder, order_id=self.order.pk, quantity=300)

        self.assertEqual(share.builder, self.builder)
        self.assertEqual(share.taken, 300)
        self.assertEqual(share.credited, 0)
        self.assertEqual(self._refresh().status, Order.Status.IN_PROGRESS)

    def test_taking_writes_a_taken_event(self):
        share = take_order(user=self.builder, order_id=self.order.pk, quantity=300)

        event = OrderEvent.objects.get(order=self.order, kind=OrderEvent.Kind.TAKEN)
        self.assertEqual(event.actor, self.builder)
        self.assertEqual(event.assignment, share)

    def test_taking_again_raises_the_same_share(self):
        take_order(user=self.builder, order_id=self.order.pk, quantity=300)
        take_order(user=self.builder, order_id=self.order.pk, quantity=200)

        share = OrderAssignment.objects.get(order=self.order, builder=self.builder)
        self.assertEqual(share.taken, 500)
        self.assertEqual(OrderAssignment.objects.filter(order=self.order).count(), 1)

    def test_everything_taken_distributes_the_order(self):
        take_order(user=self.builder, order_id=self.order.pk, quantity=600)
        take_order(user=self.other, order_id=self.order.pk, quantity=400)

        self.assertEqual(self._refresh().status, Order.Status.DISTRIBUTED)

    def test_cannot_take_more_than_is_free(self):
        take_order(user=self.other, order_id=self.order.pk, quantity=700)

        with self.assertRaises(ValidationError):
            take_order(user=self.builder, order_id=self.order.pk, quantity=301)

        self.assertFalse(
            OrderAssignment.objects.filter(
                order=self.order, builder=self.builder
            ).exists()
        )

    def test_quantity_must_be_positive(self):
        for quantity in (0, -5):
            with self.subTest(quantity=quantity):
                with self.assertRaises(ValidationError):
                    take_order(
                        user=self.builder, order_id=self.order.pk, quantity=quantity
                    )

        self.assertFalse(OrderAssignment.objects.exists())

    def test_access_level_is_checked(self):
        middle = self._order(Order.AccessLevel.MIDDLE)

        with self.assertRaises(ValidationError):
            take_order(user=self.builder, order_id=middle.pk, quantity=10)

        BuilderProfile.objects.create(user=self.builder, level=Order.AccessLevel.MIDDLE)
        take_order(user=self.builder, order_id=middle.pk, quantity=10)

        self.assertEqual(OrderAssignment.objects.get(order=middle).taken, 10)

    def test_closed_orders_cannot_be_taken(self):
        for status in (Order.Status.COMPLETED, Order.Status.CANCELLED):
            with self.subTest(status=status):
                Order.objects.filter(pk=self.order.pk).update(status=status)

                with self.assertRaises(ValidationError):
                    take_order(user=self.manager, order_id=self.order.pk, quantity=10)

    def test_users_without_access_cannot_take(self):
        nobody = make_user("nobody")

        with self.assertRaises(ValidationError):
            take_order(user=nobody, order_id=self.order.pk, quantity=10)

    def test_a_manager_can_take_too(self):
        share = take_order(user=self.manager, order_id=self.order.pk, quantity=50)

        self.assertEqual(share.taken, 50)


class TestRecalculateStatus(TakeOrderTestCase):
    """recalculate_status"""

    def _set_share(self, taken, credited):
        OrderAssignment.objects.update_or_create(
            order=self.order,
            builder=self.builder,
            defaults={"taken": taken, "credited": credited},
        )
        recalculate_status(self.order)

        return self._refresh().status

    def test_status_follows_the_shares(self):
        self.assertEqual(self._set_share(0, 0), Order.Status.NEW)
        self.assertEqual(self._set_share(400, 0), Order.Status.IN_PROGRESS)
        self.assertEqual(self._set_share(1000, 0), Order.Status.DISTRIBUTED)
        self.assertEqual(self._set_share(1000, 600), Order.Status.DISTRIBUTED)
        self.assertEqual(self._set_share(1000, 1000), Order.Status.COMPLETED)

    def test_everything_released_makes_the_order_new_again(self):
        self._set_share(400, 0)

        self.assertEqual(self._set_share(0, 0), Order.Status.NEW)

    def test_cancelled_orders_stay_cancelled(self):
        Order.objects.filter(pk=self.order.pk).update(status=Order.Status.CANCELLED)
        self.order.refresh_from_db()

        self.assertEqual(self._set_share(1000, 1000), Order.Status.CANCELLED)