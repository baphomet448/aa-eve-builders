"""The command that clears the orders and keeps the settings"""

# Standard Library
from datetime import timedelta
from decimal import Decimal
from io import StringIO

# Django
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

# AA EVE Builders
from evebuilders.models import (
    BuilderProfile,
    ContractRecord,
    ContractSource,
    Destination,
    DiscordConfig,
    Order,
    OrderAssignment,
    OrderEvent,
    OrderSequence,
)
from evebuilders.orders import create_order
from evebuilders.tests.test_take_discard_views import ViewsTestCase

WEBHOOK = "https://discord.com/api/webhooks/1/token"


class ResetTestCase(ViewsTestCase):
    """
    Two orders (self.order and self.middle). The builder self.other took 20 of the
    first, the admin self.manager (who sees every order) took 10 of the second, and
    there is a contract for each of them.
    """

    def setUp(self):
        self._take(self.other, 20)
        self._take(self.manager, 10, order=self.middle)
        self.rs_share = OrderAssignment.objects.get(
            order=self.order, builder=self.other
        )
        self.rs_middle_share = OrderAssignment.objects.get(
            order=self.middle, builder=self.manager
        )
        self.rs_contract(1, self.order, self.rs_share)
        self.rs_contract(2, self.middle, self.rs_middle_share)

    @staticmethod
    def rs_contract(contract_id, order, share):
        return ContractRecord.objects.create(
            contract_id=contract_id,
            order=order,
            assignment=share,
            issuer_character_id=1,
            quantity=5,
            price=Decimal("5000000"),
            state=ContractRecord.State.OUTSTANDING,
        )

    @staticmethod
    def rs_settings():
        """What must survive: one of each kind of settings"""

        ContractSource(corporation_id=98000001, corporation_name="Test Corp").save()
        DiscordConfig.objects.create(new_order_webhook_url=WEBHOOK)
        Destination.objects.create(
            label="Jita IV", system_id=30000142, system_name="Jita"
        )

    @staticmethod
    def rs_run(*args) -> str:
        out = StringIO()
        call_command("evebuilders_reset_orders", *args, stdout=out)

        return out.getvalue()

    @staticmethod
    def rs_counts() -> dict:
        return {
            "orders": Order.objects.count(),
            "shares": OrderAssignment.objects.count(),
            "contracts": ContractRecord.objects.count(),
        }


class TestTheDryRun(ResetTestCase):
    """Without --yes nothing is deleted"""

    def test_nothing_is_deleted_and_it_says_what_it_would_delete(self):
        before = self.rs_counts()
        events = OrderEvent.objects.count()

        output = self.rs_run()

        self.assertEqual(self.rs_counts(), before)
        self.assertEqual(OrderEvent.objects.count(), events)
        self.assertIn("Orders to delete: 2", output)
        self.assertIn(self.order.number, output)
        self.assertIn(self.middle.number, output)
        self.assertIn("Contracts to delete: 2", output)
        self.assertIn("Nothing was deleted. Run it again with --yes to delete.", output)

    def test_it_says_what_stays(self):
        output = self.rs_run("--keep", self.order.number)

        self.assertIn("Orders to delete: 1", output)
        self.assertIn(f"Orders that stay: {self.order.number}", output)
        self.assertIn("Stays: the settings", output)

    def test_an_empty_database_has_nothing_to_delete(self):
        self.rs_run("--yes")

        self.assertIn("There is nothing to delete.", self.rs_run())


class TestTheRealRun(ResetTestCase):
    """With --yes the orders go and the settings stay"""

    def test_the_orders_and_what_belongs_to_them_are_deleted(self):
        output = self.rs_run("--yes")

        self.assertEqual(self.rs_counts(), {"orders": 0, "shares": 0, "contracts": 0})
        self.assertFalse(OrderEvent.objects.filter(order__isnull=False).exists())
        self.assertIn("Deleted: 2 orders", output)

    def test_a_contract_that_belongs_to_no_order_is_deleted_too(self):
        ContractRecord.objects.create(
            contract_id=3,
            issuer_character_id=1,
            state=ContractRecord.State.INVALID,
        )

        self.rs_run("--yes")

        self.assertEqual(ContractRecord.objects.count(), 0)

    def test_the_settings_stay(self):
        self.rs_settings()
        BuilderProfile.objects.create(user=self.builder, level=Order.AccessLevel.SENIOR)

        self.rs_run("--yes")

        self.assertEqual(ContractSource.get_solo().corporation_name, "Test Corp")
        self.assertEqual(DiscordConfig.objects.get().new_order_webhook_url, WEBHOOK)
        self.assertEqual(Destination.objects.get().label, "Jita IV")
        self.assertEqual(
            BuilderProfile.objects.get(user=self.builder).level,
            Order.AccessLevel.SENIOR,
        )

    def test_the_events_that_belong_to_no_order_stay(self):
        event = OrderEvent.objects.create(
            kind=OrderEvent.Kind.LEVEL_CHANGED,
            description="Level of X: Base -> Middle",
        )

        self.rs_run("--yes")

        self.assertTrue(OrderEvent.objects.filter(pk=event.pk).exists())

    def test_the_numbers_are_not_used_again(self):
        sequences = sorted(OrderSequence.objects.values_list("date", "last_number"))
        old_numbers = {self.order.number, self.middle.number}

        self.rs_run("--yes")
        new = create_order(
            user=self.manager,
            eve_type=self.eve_type,
            quantity=5,
            unit_price=Decimal("1000"),
            due_date=timezone.localdate() + timedelta(days=3),
        )

        self.assertNotIn(new.number, old_numbers)
        # The counters of the days were not touched by the command, only used
        today = timezone.localdate()
        after = dict(OrderSequence.objects.values_list("date", "last_number"))
        for day, last in sequences:
            expected = last + 1 if day == today else last
            self.assertEqual(after[day], expected)


class TestKeep(ResetTestCase):
    """--keep leaves chosen orders alone"""

    def test_a_kept_order_stays_with_everything_that_belongs_to_it(self):
        history = OrderEvent.objects.filter(order=self.order).count()

        output = self.rs_run("--yes", "--keep", self.order.number)

        self.assertEqual(
            list(Order.objects.values_list("number", flat=True)), [self.order.number]
        )
        self.assertEqual(OrderAssignment.objects.get().order, self.order)
        self.assertEqual(ContractRecord.objects.get().contract_id, 1)
        self.assertEqual(OrderEvent.objects.filter(order=self.order).count(), history)
        self.assertIn("Deleted: 1 orders", output)

    def test_several_orders_can_be_kept(self):
        self.rs_run("--yes", "--keep", self.order.number, self.middle.number)

        self.assertEqual(Order.objects.count(), 2)
        self.assertEqual(ContractRecord.objects.count(), 2)

    def test_an_unknown_number_stops_everything(self):
        before = self.rs_counts()

        with self.assertRaises(CommandError) as caught:
            self.rs_run("--yes", "--keep", self.order.number, "N20000101-9")

        self.assertIn("N20000101-9", str(caught.exception))
        self.assertEqual(self.rs_counts(), before)
