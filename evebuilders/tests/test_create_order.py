"""Order creation tests"""

# Standard Library
from datetime import timedelta
from decimal import Decimal

# Django
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

# EVE Universe
from eveuniverse.models import EveCategory, EveGroup, EveType

# AA EVE Builders
from evebuilders.models import ContractSource, Order, OrderEvent, OrderSequence
from evebuilders.orders import create_order
from evebuilders.tests.test_views import make_user

User = get_user_model()


class TestCreateOrder(TestCase):
    """create_order"""

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

    def _data(self, **overrides):
        data = {
            "user": self.manager,
            "eve_type": self.eve_type,
            "quantity": 500,
            "unit_price": Decimal("1000000.00"),
            "due_date": timezone.localdate() + timedelta(days=7),
        }
        data.update(overrides)

        return data

    def test_creates_a_corporate_order_with_defaults(self):
        order = create_order(**self._data())

        today = timezone.localdate()
        self.assertEqual(order.number, f"N{today:%Y%m%d}-1")
        self.assertEqual(order.kind, Order.Kind.CORPORATE)
        self.assertEqual(order.status, Order.Status.NEW)
        self.assertEqual(order.priority, Order.Priority.MEDIUM)
        self.assertEqual(order.access_level, Order.AccessLevel.BASE)
        self.assertEqual(order.created_by, self.manager)
        self.assertEqual(order.updated_by, self.manager)
        # The creator's main character is in "Test Corp" (see make_user)
        self.assertEqual(order.receiver_type, Order.ReceiverType.CORPORATION)
        self.assertEqual(order.receiver_id, 98000001)
        self.assertEqual(order.receiver_name, "Test Corp")

    def test_writes_a_created_event(self):
        order = create_order(**self._data())

        event = OrderEvent.objects.get(order=order)
        self.assertEqual(event.kind, OrderEvent.Kind.CREATED)
        self.assertEqual(event.actor, self.manager)
        self.assertIn("Punisher", event.description)

    def test_receiver_is_the_connected_source_corporation(self):
        ContractSource.objects.create(
            corporation_id=98000999, corporation_name="Source Corp"
        )

        order = create_order(**self._data())

        self.assertEqual(order.receiver_id, 98000999)
        self.assertEqual(order.receiver_name, "Source Corp")

    def test_user_without_main_character_cannot_create_orders(self):
        user = User.objects.create_user("nomain")

        with self.assertRaises(ValidationError):
            create_order(**self._data(user=user))

        self.assertFalse(Order.objects.exists())

    def test_invalid_values_are_rejected_and_use_no_number(self):
        bad_values = {
            "quantity": 0,
            "unit_price": Decimal("-1"),
            "access_level": 9,
            "priority": "URGENT",
        }

        for field, value in bad_values.items():
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    create_order(**self._data(**{field: value}))

        self.assertFalse(Order.objects.exists())
        self.assertFalse(OrderSequence.objects.exists())

    def test_due_date_in_the_past_is_rejected(self):
        yesterday = timezone.localdate() - timedelta(days=1)

        with self.assertRaises(ValidationError) as caught:
            create_order(**self._data(due_date=yesterday))

        self.assertIn("due_date", caught.exception.message_dict)
        self.assertFalse(Order.objects.exists())

    def test_consecutive_orders_and_options(self):
        first = create_order(**self._data())
        second = create_order(
            **self._data(
                priority=Order.Priority.HIGH,
                access_level=Order.AccessLevel.SENIOR,
                destination="Jita",
                note="Urgent batch",
            )
        )

        self.assertTrue(first.number.endswith("-1"))
        self.assertTrue(second.number.endswith("-2"))
        self.assertEqual(second.priority, Order.Priority.HIGH)
        self.assertEqual(second.access_level, Order.AccessLevel.SENIOR)
        self.assertEqual(second.destination, "Jita")
        self.assertEqual(second.note, "Urgent batch")