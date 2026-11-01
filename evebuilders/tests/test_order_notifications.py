"""Notifications sent by order events (Discord is mocked out)"""

# Standard Library
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

# Django
from django.core.exceptions import ValidationError
from django.utils import timezone

# AA EVE Builders
from evebuilders.notifications import CHANNEL_COMPLETE, CHANNEL_NEW_ORDER
from evebuilders.orders import create_order, discard_share
from evebuilders.tests.test_notifications import SettingsMixin
from evebuilders.tests.test_take_discard_views import ViewsTestCase

DELAY = "evebuilders.tasks.send_discord_notification.delay"
URL = "https://discord.com/api/webhooks/1/abc"


class TestOrderNotifications(SettingsMixin, ViewsTestCase):
    """Creating an order and giving items back announce themselves"""

    def _create(self, **overrides):
        data = {
            "user": self.manager,
            "eve_type": self.eve_type,
            "quantity": 10,
            "unit_price": Decimal("100.00"),
            "due_date": timezone.localdate() + timedelta(days=7),
        }
        data.update(overrides)

        return create_order(**data)

    def test_a_new_order_is_announced_after_the_commit(self):
        self.configure(NEW_ORDER_WEBHOOK_URL=URL, NEW_ORDER_THREAD_ID="")

        with patch(DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True):
                order = self._create()

        delay.assert_called_once()
        channel, payload = delay.call_args.args
        self.assertEqual(channel, CHANNEL_NEW_ORDER)
        self.assertIn(order.number, str(payload))

    def test_an_order_that_is_not_created_is_not_announced(self):
        self.configure(NEW_ORDER_WEBHOOK_URL=URL, NEW_ORDER_THREAD_ID="")

        with patch(DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                with self.assertRaises(ValidationError):
                    self._create(quantity=0)

        self.assertEqual(callbacks, [])
        delay.assert_not_called()

    def test_nothing_is_queued_without_a_webhook(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            self._create()

        self.assertEqual(callbacks, [])

    def test_giving_items_back_is_announced(self):
        self._take(self.builder, 5)
        self.configure(COMPLETE_WEBHOOK_URL=URL, COMPLETE_THREAD_ID="")

        with patch(DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True):
                discard_share(user=self.builder, order_id=self.order.pk)

        delay.assert_called_once()
        channel, payload = delay.call_args.args
        self.assertEqual(channel, CHANNEL_COMPLETE)
        self.assertIn("Отказ от 5 позиций", payload["embeds"][0]["description"])

    def test_a_refused_discard_is_not_announced(self):
        self.configure(COMPLETE_WEBHOOK_URL=URL, COMPLETE_THREAD_ID="")

        with patch(DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                with self.assertRaises(ValidationError):
                    discard_share(user=self.builder, order_id=self.order.pk)

        self.assertEqual(callbacks, [])
        delay.assert_not_called()