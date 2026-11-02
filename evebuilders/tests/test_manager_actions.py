"""What managers can do with shares and contracts (Discord is mocked out)"""

# Standard Library
from datetime import timedelta
from unittest.mock import patch

# Django
from django.core.exceptions import ValidationError
from django.utils import timezone

# AA EVE Builders
from evebuilders.manager_actions import credit_manually, release_share
from evebuilders.matching import Outcome, classify_contract
from evebuilders.models import ContractRecord, Order, OrderAssignment, OrderEvent
from evebuilders.notifications import CHANNEL_COMPLETE
from evebuilders.tests.test_messages import fields_of
from evebuilders.tests.test_notifications import SettingsMixin
from evebuilders.tests.test_take_discard_views import ViewsTestCase

DELAY = "evebuilders.tasks.send_discord_notification.delay"
URL = "https://discord.com/api/webhooks/1/abc"


class ManagerActionsTestCase(SettingsMixin, ViewsTestCase):
    """A builder with a share of 400 of an order of 1000 (1 000 000 ISK each)"""

    def setUp(self):
        self.share = self._take(self.builder, 400)

    def _record(self, state, quantity, contract_id=1001, **extra):
        return ContractRecord.objects.create(
            contract_id=contract_id,
            order=self.order,
            assignment=self.share,
            issuer_character_id=1,
            quantity=quantity,
            state=state,
            **extra,
        )

    def _release(self, **kwargs):
        return release_share(
            actor=self.manager,
            order_id=self.order.pk,
            assignment_id=self.share.pk,
            **kwargs,
        )

    def _credit(self, quantity, **kwargs):
        return credit_manually(
            actor=self.manager,
            order_id=self.order.pk,
            assignment_id=self.share.pk,
            quantity=quantity,
            **kwargs,
        )

    def _refresh(self):
        self.share.refresh_from_db()
        self.order.refresh_from_db()


class TestReleaseShare(ManagerActionsTestCase):
    """release_share"""

    def test_releases_everything_that_can_be_released(self):
        self.assertEqual(self._release(), 400)

        self._refresh()
        self.assertEqual(self.share.taken, 0)
        self.assertEqual(self.order.status, Order.Status.NEW)
        event = OrderEvent.objects.get(kind=OrderEvent.Kind.RELEASED)
        self.assertEqual(event.actor, self.manager)
        self.assertEqual(event.assignment, self.share)

    def test_part_of_the_share_can_be_released(self):
        self.assertEqual(self._release(quantity=150), 150)

        self._refresh()
        self.assertEqual(self.share.taken, 250)
        self.assertEqual(self.order.status, Order.Status.IN_PROGRESS)

    def test_credited_and_waiting_items_stay_with_the_builder(self):
        OrderAssignment.objects.filter(pk=self.share.pk).update(credited=100)
        self._record(ContractRecord.State.OUTSTANDING, 150)

        self.assertEqual(self._release(), 150)

        self._refresh()
        self.assertEqual(self.share.taken, 250)

    def test_nothing_to_release(self):
        self._record(ContractRecord.State.OUTSTANDING, 400)

        with self.assertRaises(ValidationError):
            self._release()

        self._refresh()
        self.assertEqual(self.share.taken, 400)

    def test_the_quantity_must_be_within_what_can_be_released(self):
        for quantity in (0, -1, 401):
            with self.subTest(quantity=quantity):
                with self.assertRaises(ValidationError):
                    self._release(quantity=quantity)

        self._refresh()
        self.assertEqual(self.share.taken, 400)

    def test_only_managers_can_release(self):
        with self.assertRaises(ValidationError):
            release_share(
                actor=self.builder,
                order_id=self.order.pk,
                assignment_id=self.share.pk,
            )

        self._refresh()
        self.assertEqual(self.share.taken, 400)

    def test_there_is_no_time_limit(self):
        Order.objects.filter(pk=self.order.pk).update(
            created_at=timezone.now() - timedelta(days=6),
            due_date=timezone.localdate() + timedelta(days=2),
        )

        self.assertEqual(self._release(), 400)

    def test_a_share_of_another_order_is_refused(self):
        another = self._order()  # a second order, also for Base builders
        other_share = self._take(self.other, 10, order=another)

        with self.assertRaises(ValidationError):
            release_share(
                actor=self.manager,
                order_id=self.order.pk,
                assignment_id=other_share.pk,
            )

    def test_it_is_announced_after_the_commit(self):
        self.configure(COMPLETE_WEBHOOK_URL=URL, COMPLETE_THREAD_ID="")

        with patch(DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self._release(quantity=100)

        delay.assert_called_once()
        channel, payload = delay.call_args.args
        self.assertEqual(channel, CHANNEL_COMPLETE)
        self.assertIn("снял с исполнителя 100 позиций", str(payload))
        self.assertEqual(fields_of(payload)["Свободно в заказе"], "700 шт")

    def test_a_refused_release_is_not_announced(self):
        self.configure(COMPLETE_WEBHOOK_URL=URL, COMPLETE_THREAD_ID="")

        with patch(DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                with self.assertRaises(ValidationError):
                    self._release(quantity=999)

        self.assertEqual(callbacks, [])
        delay.assert_not_called()


class TestCreditManually(ManagerActionsTestCase):
    """credit_manually"""

    def test_credits_and_writes_an_event(self):
        self.assertEqual(self._credit(150, comment="delivered in person"), 150)

        self._refresh()
        self.assertEqual(self.share.credited, 150)
        event = OrderEvent.objects.get(kind=OrderEvent.Kind.MANUAL_CREDIT)
        self.assertEqual(event.actor, self.manager)
        self.assertEqual(event.assignment, self.share)
        self.assertIn("delivered in person", event.description)

    def test_the_last_items_complete_the_order(self):
        take_rest = self._take(self.other, 600)
        credit_rest = credit_manually(
            actor=self.manager,
            order_id=self.order.pk,
            assignment_id=take_rest.pk,
            quantity=600,
        )
        self._credit(400)

        self._refresh()
        self.assertEqual(credit_rest, 600)
        self.assertEqual(self.order.status, Order.Status.COMPLETED)

    def test_it_cannot_credit_more_than_is_left(self):
        for quantity in (0, -1, 401):
            with self.subTest(quantity=quantity):
                with self.assertRaises(ValidationError):
                    self._credit(quantity)

        self._refresh()
        self.assertEqual(self.share.credited, 0)

    def test_nothing_left_to_credit(self):
        self._credit(400)

        with self.assertRaises(ValidationError):
            self._credit(1)

    def test_waiting_contracts_reserve_their_items(self):
        self._record(ContractRecord.State.OUTSTANDING, 300)

        with self.assertRaises(ValidationError):
            self._credit(150)  # only 100 are left

        self.assertEqual(self._credit(100), 100)

    def test_only_managers_can_credit(self):
        with self.assertRaises(ValidationError):
            credit_manually(
                actor=self.builder,
                order_id=self.order.pk,
                assignment_id=self.share.pk,
                quantity=10,
            )

        self._refresh()
        self.assertEqual(self.share.credited, 0)

    def test_it_closes_a_contract_without_an_order_number(self):
        # The accepted contract that has no order number in its title
        record = ContractRecord.objects.create(
            contract_id=555,
            issuer_character_id=1,
            quantity=0,
            state=ContractRecord.State.INVALID,
            reason="The contract title has no order number.",
        )

        self._credit(100, contract_id=555)

        record.refresh_from_db()
        self.assertEqual(record.state, ContractRecord.State.CREDITED)
        self.assertEqual(record.order, self.order)
        self.assertEqual(record.assignment, self.share)
        self.assertEqual(record.quantity, 100)
        self.assertEqual(record.reason, "")
        self._refresh()
        self.assertEqual(self.share.credited, 100)

    def test_a_closed_contract_is_not_counted_again_by_the_sync(self):
        ContractRecord.objects.create(
            contract_id=555,
            issuer_character_id=1,
            quantity=0,
            state=ContractRecord.State.INVALID,
        )
        self._credit(100, contract_id=555)
        contract = {
            "contract_id": 555,
            "type": "item_exchange",
            "status": "finished",
            "assignee_id": 98000001,
            "issuer_id": 1,
            "title": "",
        }

        def must_not_be_called(_contract_id):
            raise AssertionError("the items must not even be loaded")

        verdict = classify_contract(
            contract, corporation_id=98000001, items_loader=must_not_be_called
        )

        self.assertEqual(verdict.outcome, Outcome.IGNORE)

    def test_a_waiting_contract_may_be_credited_by_hand(self):
        self._record(ContractRecord.State.OUTSTANDING, 400, contract_id=777)

        # Its own items are not "reserved by another contract"
        self.assertEqual(self._credit(400, contract_id=777), 400)

        self.assertEqual(
            ContractRecord.objects.get(contract_id=777).state,
            ContractRecord.State.CREDITED,
        )

    def test_unknown_and_credited_contracts_are_refused(self):
        self._record(ContractRecord.State.CREDITED, 10, contract_id=888)

        for contract_id in (999, 888):
            with self.subTest(contract_id=contract_id):
                with self.assertRaises(ValidationError):
                    self._credit(10, contract_id=contract_id)

        self._refresh()
        self.assertEqual(self.share.credited, 0)

    def test_it_is_announced_with_who_credited_and_the_rest(self):
        self.configure(COMPLETE_WEBHOOK_URL=URL, COMPLETE_THREAD_ID="")

        with patch(DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self._credit(150, comment="paid in Jita")

        delay.assert_called_once()
        channel, payload = delay.call_args.args
        lines = payload["embeds"][0]["description"].splitlines()
        self.assertEqual(channel, CHANNEL_COMPLETE)
        self.assertIn("Зачтено вручную - 150 шт", lines)
        self.assertIn("Комментарий - paid in Jita", lines)
        self.assertIn("Остаток по заказу - 850 шт", lines)

    def test_a_refused_credit_is_not_announced(self):
        self.configure(COMPLETE_WEBHOOK_URL=URL, COMPLETE_THREAD_ID="")

        with patch(DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                with self.assertRaises(ValidationError):
                    self._credit(999)

        self.assertEqual(callbacks, [])
        delay.assert_not_called()
