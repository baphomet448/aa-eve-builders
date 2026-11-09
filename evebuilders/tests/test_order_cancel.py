"""Deleting (cancelling) an order (Discord is mocked out)"""

# Standard Library
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

# Django
from django.contrib.messages import constants, get_messages
from django.core.exceptions import ValidationError
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

# AA EVE Builders
from evebuilders.manager_actions import can_delete_order, cancel_order
from evebuilders.messages import display_name
from evebuilders.models import ContractRecord, Order, OrderEvent
from evebuilders.notifications import CHANNEL_NEW_ORDER, EMOJI_DELETED
from evebuilders.orders import create_order, my_shares, share_status, take_order
from evebuilders.tests.test_messages import fields_of
from evebuilders.tests.test_notifications import SettingsMixin
from evebuilders.tests.test_sync import SyncTestCase
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES

DELAY = "evebuilders.tasks.send_discord_notification.delay"
URL = "https://discord.com/api/webhooks/1/abc"


class CancelTestCase(SettingsMixin, ViewsTestCase):
    """The order of 1000 Punishers"""

    def _cancel(self, actor=None, order=None, **kwargs):
        return cancel_order(
            actor=actor or self.manager, order_id=(order or self.order).pk, **kwargs
        )

    def _refresh(self):
        self.order.refresh_from_db()

    def _own_order(self, user):
        """An order created by someone who is not a manager"""

        return create_order(
            user=user,
            eve_type=self.eve_type,
            quantity=10,
            unit_price=Decimal("100.00"),
            due_date=timezone.localdate() + timedelta(days=7),
        )


class TestCanDeleteOrder(CancelTestCase):
    """can_delete_order"""

    def test_a_manager_may_delete_any_order_at_any_status(self):
        for status in (
            Order.Status.NEW,
            Order.Status.IN_PROGRESS,
            Order.Status.DISTRIBUTED,
            Order.Status.COMPLETED,
        ):
            with self.subTest(status=status):
                Order.objects.filter(pk=self.order.pk).update(status=status)
                self._refresh()

                self.assertTrue(can_delete_order(self.manager, self.order))

    def test_a_cancelled_order_cannot_be_deleted_again(self):
        Order.objects.filter(pk=self.order.pk).update(status=Order.Status.CANCELLED)
        self._refresh()

        self.assertFalse(can_delete_order(self.manager, self.order))

    def test_the_creator_may_delete_a_fresh_untouched_order(self):
        own = self._own_order(self.builder)

        self.assertTrue(can_delete_order(self.builder, own))

    def test_the_creator_may_not_delete_after_an_hour(self):
        own = self._own_order(self.builder)
        Order.objects.filter(pk=own.pk).update(
            created_at=timezone.now() - timedelta(minutes=61)
        )
        own.refresh_from_db()

        self.assertFalse(can_delete_order(self.builder, own))

    def test_the_creator_may_not_delete_once_somebody_took_it(self):
        own = self._own_order(self.builder)
        take_order(user=self.other, order_id=own.pk, quantity=1)
        own.refresh_from_db()

        self.assertFalse(can_delete_order(self.builder, own))

    def test_somebody_else_may_not_delete_it(self):
        own = self._own_order(self.builder)

        self.assertFalse(can_delete_order(self.other, own))


class TestCancelOrder(CancelTestCase):
    """cancel_order"""

    def test_the_order_is_cancelled_and_the_shares_stay(self):
        share = self._take(self.builder, 400)

        order = self._cancel(reason="made by mistake")

        self._refresh()
        share.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(self.order.status, Order.Status.CANCELLED)
        self.assertEqual(self.order.updated_by, self.manager)
        self.assertEqual(share.taken, 400)
        event = OrderEvent.objects.get(kind=OrderEvent.Kind.CANCELLED)
        self.assertEqual(event.actor, self.manager)
        self.assertIn("made by mistake", event.description)

    def test_it_cannot_be_cancelled_twice(self):
        self._cancel()

        with self.assertRaises(ValidationError):
            self._cancel()

    def test_users_without_the_right_cannot_cancel(self):
        with self.assertRaises(ValidationError):
            self._cancel(actor=self.builder)

        self._refresh()
        self.assertEqual(self.order.status, Order.Status.NEW)

    def test_the_creator_may_cancel_his_own_fresh_order(self):
        own = self._own_order(self.builder)

        self._cancel(actor=self.builder, order=own)

        own.refresh_from_db()
        self.assertEqual(own.status, Order.Status.CANCELLED)

    def test_a_cancelled_order_cannot_be_taken(self):
        self._cancel()

        with self.assertRaises(ValidationError):
            self._take(self.builder, 10)

    def test_the_share_of_a_cancelled_order_says_so(self):
        share = self._take(self.builder, 400)
        self._cancel()
        share.refresh_from_db()

        self.assertEqual(share_status(share), "CANCELLED")
        self.assertEqual(my_shares(self.builder)[0]["status"], "CANCELLED")
        self.assertFalse(my_shares(self.builder)[0]["can_discard"])

    def test_it_is_announced_with_who_what_and_why(self):
        self._take(self.builder, 400)
        self.configure(NEW_ORDER_WEBHOOK_URL=URL, NEW_ORDER_THREAD_ID="")

        with patch(DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self._cancel(reason="made by mistake")

        delay.assert_called_once()
        channel, payload = delay.call_args.args
        self.assertEqual(channel, CHANNEL_NEW_ORDER)
        self.assertEqual(
            payload["embeds"][0]["description"],
            f"{EMOJI_DELETED} Заказ {self.order.number} был удален "
            f"{display_name(self.manager)}",
        )
        fields = fields_of(payload)
        self.assertEqual(fields["Количество"], "1000")
        self.assertEqual(fields["Было взято в работу"], "400 шт")
        self.assertEqual(fields["Причина"], "made by mistake")

    def test_a_refused_deletion_is_not_announced(self):
        self.configure(NEW_ORDER_WEBHOOK_URL=URL, NEW_ORDER_THREAD_ID="")

        with patch(DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                with self.assertRaises(ValidationError):
                    self._cancel(actor=self.builder)

        self.assertEqual(callbacks, [])
        delay.assert_not_called()


class TestContractsOfACancelledOrder(SyncTestCase):
    """Contracts for a cancelled order are not credited by the sync"""

    def _cancel_the_order(self):
        Order.objects.filter(pk=self.order.pk).update(status=Order.Status.CANCELLED)

    def test_an_accepted_contract_is_not_credited(self):
        self._cancel_the_order()

        report = self._process([self._finished()])

        record = ContractRecord.objects.get(contract_id=1001)
        self.share.refresh_from_db()
        self.assertEqual(report.credited, 0)
        self.assertEqual(report.invalid, 1)
        self.assertEqual(record.state, ContractRecord.State.INVALID)
        self.assertIn("cancelled", record.reason)
        self.assertEqual(self.share.credited, 0)

    def test_a_waiting_contract_becomes_invalid_at_the_next_sync(self):
        self._process([self._contract()])
        self.assertEqual(
            ContractRecord.objects.get().state, ContractRecord.State.OUTSTANDING
        )
        self._cancel_the_order()

        self._process([self._contract()])

        self.assertEqual(
            ContractRecord.objects.get().state, ContractRecord.State.INVALID
        )


@override_settings(STORAGES=TEST_STORAGES)
class TestDeleteOrderPages(CancelTestCase):
    """The Delete order button and its page"""

    def _url(self, name="delete_order"):
        return reverse(f"evebuilders:{name}", args=[self.order.pk])

    def _post(self, data=None, user=None):
        client = Client()  # fresh client: no messages left over from before
        client.force_login(user or self.manager)

        return client.post(self._url(), data or {})

    @staticmethod
    def _levels(response):
        return [m.level for m in get_messages(response.wsgi_request)]

    def test_a_manager_deletes_an_order(self):
        response = self._post({"reason": "duplicate"})

        self.assertRedirects(
            response, reverse("evebuilders:orders"), fetch_redirect_response=False
        )
        self._refresh()
        self.assertEqual(self.order.status, Order.Status.CANCELLED)
        self.assertEqual(self._levels(response), [constants.SUCCESS])

    def test_deleting_twice_is_an_error(self):
        self._post()

        response = self._post()

        self.assertRedirects(
            response, self._url("order_detail"), fetch_redirect_response=False
        )
        self.assertEqual(self._levels(response), [constants.ERROR])

    def test_builders_cannot_delete_and_get_is_not_allowed(self):
        response = self._post(user=self.builder)

        self.assertEqual(response.status_code, 302)
        self._refresh()
        self.assertEqual(self.order.status, Order.Status.NEW)

        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(self._url()).status_code, 405)

    def test_the_details_page_offers_deleting_until_it_is_done(self):
        self.client.force_login(self.manager)

        before = self.client.get(self._url("order_detail"))
        self._post()
        after = self.client.get(self._url("order_detail"))

        self.assertContains(before, self._url())
        self.assertNotContains(after, self._url())

    def test_my_orders_shows_a_cancelled_order(self):
        self._take(self.builder, 400)
        self._post()
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:my_orders"))

        self.assertContains(response, "Cancelled")
