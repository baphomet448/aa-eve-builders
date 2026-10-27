"""Discard share tests"""

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
from evebuilders.models import ContractRecord, Order, OrderAssignment, OrderEvent
from evebuilders.orders import (
    create_order,
    discard_deadline,
    discard_share,
    pending_quantity,
    releasable_quantity,
    take_order,
)
from evebuilders.tests.test_views import make_user


class DiscardTestCase(TestCase):
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
        cls.order = create_order(
            user=cls.manager,
            eve_type=cls.eve_type,
            quantity=1000,
            unit_price=Decimal("1000000.00"),
            due_date=timezone.localdate() + timedelta(days=7),
        )

    def _take(self, quantity, user=None):
        return take_order(
            user=user or self.builder, order_id=self.order.pk, quantity=quantity
        )

    def _contract(self, share, quantity, contract_id=1001, state=None):
        return ContractRecord.objects.create(
            contract_id=contract_id,
            order=self.order,
            assignment=share,
            issuer_character_id=1,
            quantity=quantity,
            state=state or ContractRecord.State.OUTSTANDING,
        )

    def _set_dates(self, created_days_ago, due_in_days):
        Order.objects.filter(pk=self.order.pk).update(
            created_at=timezone.now() - timedelta(days=created_days_ago),
            due_date=timezone.localdate() + timedelta(days=due_in_days),
        )
        self.order.refresh_from_db()

    def _discard(self, **kwargs):
        return discard_share(user=self.builder, order_id=self.order.pk, **kwargs)


class TestDiscardShare(DiscardTestCase):
    """discard_share"""

    def test_gives_the_free_part_back(self):
        share = self._take(400)

        given_back = self._discard()

        share.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(given_back, 400)
        self.assertEqual(share.taken, 0)
        self.assertEqual(share.status, "DISCARDED")
        self.assertEqual(self.order.status, Order.Status.NEW)
        event = OrderEvent.objects.get(kind=OrderEvent.Kind.DISCARDED)
        self.assertEqual(event.actor, self.builder)
        self.assertEqual(event.assignment, share)

    def test_part_of_the_share_can_be_given_back(self):
        share = self._take(400)

        self.assertEqual(self._discard(quantity=150), 150)

        share.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(share.taken, 250)
        self.assertEqual(self.order.status, Order.Status.IN_PROGRESS)

    def test_credited_items_stay_with_the_builder(self):
        share = self._take(400)
        OrderAssignment.objects.filter(pk=share.pk).update(credited=100)

        self.assertEqual(self._discard(), 300)

        share.refresh_from_db()
        self.assertEqual(share.taken, 100)
        self.assertEqual(share.credited, 100)

    def test_items_in_a_waiting_contract_stay_with_the_builder(self):
        share = self._take(400)
        self._contract(share, 250)

        self.assertEqual(self._discard(), 150)

        share.refresh_from_db()
        self.assertEqual(share.taken, 250)

    def test_nothing_to_give_back(self):
        share = self._take(400)
        self._contract(share, 400)

        with self.assertRaises(ValidationError):
            self._discard()

        share.refresh_from_db()
        self.assertEqual(share.taken, 400)

    def test_quantity_must_be_within_what_can_be_given_back(self):
        self._take(400)

        for quantity in (0, -1, 401):
            with self.subTest(quantity=quantity):
                with self.assertRaises(ValidationError):
                    self._discard(quantity=quantity)

        self.assertEqual(OrderAssignment.objects.get().taken, 400)

    def test_a_builder_without_a_share_cannot_discard(self):
        self._take(400, user=self.other)

        with self.assertRaises(ValidationError):
            self._discard()

    def test_closed_orders_cannot_be_discarded(self):
        self._take(400)

        for status in (Order.Status.COMPLETED, Order.Status.CANCELLED):
            with self.subTest(status=status):
                Order.objects.filter(pk=self.order.pk).update(status=status)

                with self.assertRaises(ValidationError):
                    self._discard()

    def test_given_back_items_can_be_taken_by_someone_else(self):
        self._take(400)
        self._discard()

        share = self._take(1000, user=self.other)

        self.assertEqual(share.taken, 1000)


class TestDiscardTimeLimit(DiscardTestCase):
    """Half of the time between creation and due date"""

    def test_deadline_is_the_middle_of_the_time(self):
        today = timezone.localdate()

        # created today, due in 7 days: the middle is 3 days from now (rounded down)
        self.assertEqual(discard_deadline(self.order), today + timedelta(days=3))

    def test_allowed_on_the_last_day_of_the_first_half(self):
        self._take(400)
        self._set_dates(created_days_ago=4, due_in_days=4)  # the middle is today

        self.assertEqual(self._discard(), 400)

    def test_refused_after_the_first_half(self):
        self._take(400)
        self._set_dates(created_days_ago=6, due_in_days=2)  # the middle was 2 days ago

        with self.assertRaises(ValidationError):
            self._discard()

        self.assertEqual(OrderAssignment.objects.get().taken, 400)


class TestSecondBatch(DiscardTestCase):
    """
    The bug of the old application: a builder took 500, delivered them and
    pressed "deliver", and while the manager had not accepted the contract he
    took 500 more. The second batch was not counted because the first one was
    still "waiting". Here the state lives on the contract, so nothing breaks.
    """

    def test_second_batch_does_not_disturb_the_first(self):
        share = self._take(500)
        contract = self._contract(share, 500)

        self._take(500)  # the second batch, while the first contract waits

        share.refresh_from_db()
        contract.refresh_from_db()
        self.assertEqual(share.taken, 1000)
        self.assertEqual(share.credited, 0)
        self.assertEqual(pending_quantity(share), 500)
        self.assertEqual(releasable_quantity(share), 500)
        self.assertEqual(contract.state, ContractRecord.State.OUTSTANDING)
        self.assertEqual(contract.quantity, 500)
        self.assertEqual(share.status, "IN_PROGRESS")

        # The manager accepts the first contract (what the ESI sync will do later)
        OrderAssignment.objects.filter(pk=share.pk).update(credited=500)
        ContractRecord.objects.filter(pk=contract.pk).update(
            state=ContractRecord.State.CREDITED
        )
        share.refresh_from_db()
        self.assertEqual(pending_quantity(share), 0)
        self.assertEqual(releasable_quantity(share), 500)

        # The second batch is delivered in its own contract
        self._contract(share, 500, contract_id=1002)
        self.assertEqual(pending_quantity(share), 500)
        self.assertEqual(releasable_quantity(share), 0)

    def test_giving_back_never_touches_the_waiting_batch(self):
        share = self._take(500)
        contract = self._contract(share, 500)
        self._take(500)

        self.assertEqual(self._discard(), 500)  # only the second batch

        share.refresh_from_db()
        contract.refresh_from_db()
        self.assertEqual(share.taken, 500)
        self.assertEqual(contract.state, ContractRecord.State.OUTSTANDING)
        self.assertEqual(contract.quantity, 500)