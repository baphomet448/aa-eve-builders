"""The "taken" notification (Discord is mocked out)"""

# Standard Library
from unittest.mock import patch

# Django
from django.core.exceptions import ValidationError

# AA EVE Builders
from evebuilders import app_settings
from evebuilders.messages import display_name
from evebuilders.notifications import CHANNEL_COMPLETE
from evebuilders.tests.test_messages import fields_of
from evebuilders.tests.test_notifications import SettingsMixin
from evebuilders.tests.test_take_discard_views import ViewsTestCase

DELAY = "evebuilders.tasks.send_discord_notification.delay"
URL = "https://discord.com/api/webhooks/1/abc"


class TestTakenNotification(SettingsMixin, ViewsTestCase):
    """Taking part of an order announces itself"""

    def setUp(self):
        self.configure(COMPLETE_WEBHOOK_URL=URL, COMPLETE_THREAD_ID="")

    def test_taking_is_announced(self):
        with patch(DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self._take(self.builder, 300)

        delay.assert_called_once()
        channel, payload = delay.call_args.args
        self.assertEqual(channel, CHANNEL_COMPLETE)
        self.assertEqual(
            payload["embeds"][0]["description"],
            f"Заказ {self.order.number} отдан в работу - {display_name(self.builder)}",
        )
        fields = fields_of(payload)
        self.assertEqual(fields["Количество"], "300")
        self.assertEqual(fields["Остаток свободных позиций в заказе"], "700")
        self.assertEqual(fields["Цена за единицу"], "1 000 000,00 ISK 1 миллион")
        self.assertEqual(fields["Цена за все"], "300 000 000,00 ISK 300 миллионов")

    def test_it_can_be_switched_off(self):
        with patch.object(app_settings, "EVEBUILDERS_DISCORD_NOTIFY_TAKEN", False):
            with patch(DELAY) as delay:
                with self.captureOnCommitCallbacks(execute=True) as callbacks:
                    self._take(self.builder, 300)

        self.assertEqual(callbacks, [])
        delay.assert_not_called()

    def test_a_refused_take_is_not_announced(self):
        with patch(DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                with self.assertRaises(ValidationError):
                    self._take(self.builder, 1001)

        self.assertEqual(callbacks, [])
        delay.assert_not_called()