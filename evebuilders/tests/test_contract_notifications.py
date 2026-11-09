"""Notifications sent by contract events (Discord is mocked out)"""

# Standard Library
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

# Django
from django.test import TestCase
from django.utils import timezone

# AA EVE Builders
from evebuilders.contracts import EsiTokenError, EsiUnavailable
from evebuilders.models import ContractRecord, ContractSource
from evebuilders.notifications import CHANNEL_COMPLETE
from evebuilders.orders import create_order, take_order
from evebuilders.sync import sync_contracts
from evebuilders.tests.test_messages import fields_of
from evebuilders.tests.test_notifications import SettingsMixin
from evebuilders.tests.test_sync import SyncTestCase

DELAY = "evebuilders.tasks.send_discord_notification.delay"
SYNC = "evebuilders.sync"
URL = "https://discord.com/api/webhooks/1/abc"
WAITING = "ОЖИДАЕТ ВАЛИДАЦИИ КОНТРАКТА"


class TestContractNotifications(SettingsMixin, SyncTestCase):
    """Contracts announce themselves in Discord"""

    def setUp(self):
        self.configure(COMPLETE_WEBHOOK_URL=URL, COMPLETE_THREAD_ID="")

    def _announced(self, action):
        """Run an action, return (channel, payload) of every message it queued"""

        with patch(DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True):
                action()

        return [call.args for call in delay.call_args_list]

    @staticmethod
    def _description(message):
        return message[1]["embeds"][0]["description"]

    def test_a_waiting_contract_is_announced_once(self):
        first = self._announced(lambda: self._process([self._contract()]))
        again = self._announced(lambda: self._process([self._contract()]))

        self.assertEqual(len(first), 1)
        channel, payload = first[0]
        self.assertEqual(channel, CHANNEL_COMPLETE)
        self.assertIn("Контракт на 5 позиций", self._description(first[0]))
        self.assertIn("Контракт 500,00 ISK", self._description(first[0]))
        self.assertEqual(fields_of(payload)["СТАТУС"], WAITING)
        self.assertEqual(fields_of(payload)["Заказ"], self.order.number)
        self.assertEqual(again, [])

    def test_an_accepted_contract_is_reported_with_the_acceptor_and_the_rest(self):
        sent = self._announced(lambda: self._process([self._finished()]))

        self.assertEqual(len(sent), 1)
        lines = self._description(sent[0]).splitlines()
        name = self.acceptor.profile.main_character.character_name
        self.assertIn("Контракт на 5 позиций", lines)
        self.assertIn(f"Контракт принял - {name}", lines)
        self.assertIn("Остаток по заказу - 5 шт", lines)

    def test_the_last_delivery_says_the_order_is_complete(self):
        order = create_order(
            user=self.manager,
            eve_type=self.eve_type,
            quantity=5,
            unit_price=Decimal("100.00"),
            due_date=timezone.localdate() + timedelta(days=7),
        )
        take_order(user=self.builder, order_id=order.pk, quantity=5)

        sent = self._announced(
            lambda: self._process(
                [self._finished(title=order.number, date_issued="2099-01-01T00:00:00Z")]
            )
        )

        description = self._description(sent[0])
        self.assertIn("Заказ завершен полностью - 5 шт", description)
        self.assertNotIn("Остаток", description)

    def test_waiting_and_then_credited_are_two_messages(self):
        sent = self._announced(
            lambda: (
                self._process([self._contract()]),
                self._process([self._finished()]),
            )
        )

        self.assertEqual(len(sent), 2)
        self.assertEqual(fields_of(sent[0][1])["СТАТУС"], WAITING)
        self.assertIn("Контракт принял", self._description(sent[1]))

    def test_an_invalid_contract_is_announced_once_with_the_reason(self):
        first = self._announced(lambda: self._process([self._contract(price=499.0)]))
        again = self._announced(lambda: self._process([self._contract(price=499.0)]))

        self.assertEqual(len(first), 1)
        fields = fields_of(first[0][1])
        self.assertEqual(fields["Заказ"], self.order.number)
        self.assertEqual(
            fields["Причина"], ContractRecord.objects.get().reason_in("ru")
        )
        self.assertIn("не засчитан", self._description(first[0]))
        self.assertEqual(again, [])

    def test_an_invalid_contract_without_an_order_has_no_order_field(self):
        sent = self._announced(
            lambda: self._process([self._contract(title="N20990101-1")])
        )

        self.assertEqual(len(sent), 1)
        fields = fields_of(sent[0][1])
        self.assertNotIn("Заказ", fields)
        self.assertIn("Причина", fields)

    def test_foreign_contracts_are_not_announced(self):
        sent = self._announced(
            lambda: self._process([self._contract(assignee_id=12345)])
        )

        self.assertEqual(sent, [])

    def test_ended_contracts_are_not_announced(self):
        self._process([self._contract()])

        sent = self._announced(
            lambda: self._process([self._contract(status="deleted")])
        )

        self.assertEqual(sent, [])


class TestTokenFailureNotification(SettingsMixin, TestCase):
    """A token that stops working is announced once"""

    def setUp(self):
        self.configure(COMPLETE_WEBHOOK_URL=URL, COMPLETE_THREAD_ID="")
        ContractSource.objects.create(
            corporation_id=98000001, corporation_name="Test Corp"
        )

    def _sync(self, error):
        with patch(DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True):
                with patch(f"{SYNC}.fetch_corporation_contracts", side_effect=error):
                    sync_contracts()

        return [call.args for call in delay.call_args_list]

    def test_the_failure_is_announced_once(self):
        first = self._sync(EsiTokenError("refused"))
        second = self._sync(EsiTokenError("refused"))

        self.assertEqual(len(first), 1)
        payload = first[0][1]
        fields = fields_of(payload)
        self.assertEqual(fields["Корпорация"], "Test Corp")
        self.assertEqual(fields["Причина"], "refused")
        self.assertIn("перестал работать", payload["embeds"][0]["description"])
        self.assertEqual(second, [])

    def test_esi_being_down_is_not_a_token_failure(self):
        self.assertEqual(self._sync(EsiUnavailable("down")), [])

    def test_a_token_that_works_again_and_fails_again_is_announced_again(self):
        self._sync(EsiTokenError("refused"))
        ContractSource.objects.update(token_ok=True)  # reconnected in Settings

        sent = self._sync(EsiTokenError("refused again"))

        self.assertEqual(len(sent), 1)
