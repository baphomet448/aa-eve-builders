"""Webhooks set in the Django admin, and the fallback to local.py"""

# Standard Library
from unittest.mock import patch

# Django
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders import app_settings
from evebuilders.models import DiscordConfig
from evebuilders.notifications import (
    CHANNEL_COMPLETE,
    CHANNEL_NEW_ORDER,
    _webhook,
    deliver,
    notify,
    notify_taken_enabled,
)
from evebuilders.tests.test_notifications import (
    OTHER_URL,
    POST,
    URL,
    SettingsMixin,
    fake_response,
)
from evebuilders.tests.test_views import TEST_STORAGES

DELAY = "evebuilders.tasks.send_discord_notification.delay"
User = get_user_model()


class TestWhereTheWebhookComes(SettingsMixin, TestCase):
    """The admin wins, local.py is the fallback"""

    def test_without_a_row_the_settings_are_used(self):
        self.configure(NEW_ORDER_WEBHOOK_URL=URL, NEW_ORDER_THREAD_ID="7")

        self.assertEqual(_webhook(CHANNEL_NEW_ORDER), (URL, "7"))

    def test_the_admin_wins_over_the_settings(self):
        self.configure(NEW_ORDER_WEBHOOK_URL=URL, NEW_ORDER_THREAD_ID="7")
        DiscordConfig.objects.create(
            new_order_webhook_url=OTHER_URL, new_order_thread_id="42"
        )

        self.assertEqual(_webhook(CHANNEL_NEW_ORDER), (OTHER_URL, "42"))

    def test_an_empty_value_falls_back_to_the_settings(self):
        self.configure(NEW_ORDER_WEBHOOK_URL=URL, NEW_ORDER_THREAD_ID="7")
        DiscordConfig.objects.create(complete_webhook_url=OTHER_URL)

        self.assertEqual(_webhook(CHANNEL_NEW_ORDER), (URL, "7"))
        self.assertEqual(_webhook(CHANNEL_COMPLETE), (OTHER_URL, ""))

    def test_the_thread_belongs_to_the_url_it_comes_with(self):
        self.configure(NEW_ORDER_WEBHOOK_URL=URL, NEW_ORDER_THREAD_ID="7")
        DiscordConfig.objects.create(new_order_webhook_url=OTHER_URL)

        # The thread of the setting is not mixed with the URL from the admin
        self.assertEqual(_webhook(CHANNEL_NEW_ORDER), (OTHER_URL, ""))

    def test_nothing_anywhere_means_no_webhook(self):
        self.configure(NEW_ORDER_WEBHOOK_URL="", NEW_ORDER_THREAD_ID="")

        self.assertEqual(_webhook(CHANNEL_NEW_ORDER), ("", ""))

    def test_an_unknown_channel_is_refused(self):
        with self.assertRaises(ValueError):
            _webhook("nonsense")

    @patch(POST, return_value=fake_response(204))
    def test_a_message_goes_to_the_url_from_the_admin(self, mock_post):
        self.configure(COMPLETE_WEBHOOK_URL="")
        DiscordConfig.objects.create(complete_webhook_url=OTHER_URL)

        self.assertEqual(deliver(CHANNEL_COMPLETE, {"content": "x"}), "sent")

        self.assertEqual(mock_post.call_args.args[0], OTHER_URL)

    @patch(POST)
    def test_a_change_in_the_admin_works_at_once(self, mock_post):
        mock_post.return_value = fake_response(204)
        self.configure(COMPLETE_WEBHOOK_URL="")

        before = deliver(CHANNEL_COMPLETE, {"content": "x"})
        DiscordConfig.objects.create(complete_webhook_url=URL)
        after = deliver(CHANNEL_COMPLETE, {"content": "x"})

        self.assertEqual((before, after), ("skipped", "sent"))

    def test_a_notification_is_queued_when_only_the_admin_has_a_url(self):
        self.configure(COMPLETE_WEBHOOK_URL="")
        DiscordConfig.objects.create(complete_webhook_url=URL)

        with patch(DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True):
                notify(CHANNEL_COMPLETE, {"content": "x"})

        delay.assert_called_once()


class TestNotifyTakenChoice(TestCase):
    """The choice to announce that a builder took a part of an order"""

    def test_without_a_row_the_setting_decides(self):
        for value in (True, False):
            with self.subTest(value=value):
                with patch.object(
                    app_settings, "EVEBUILDERS_DISCORD_NOTIFY_TAKEN", value
                ):
                    self.assertEqual(notify_taken_enabled(), value)

    def test_unknown_in_the_admin_means_the_setting_decides(self):
        DiscordConfig.objects.create(notify_taken=None)

        with patch.object(app_settings, "EVEBUILDERS_DISCORD_NOTIFY_TAKEN", False):
            self.assertFalse(notify_taken_enabled())

    def test_a_choice_in_the_admin_wins(self):
        config = DiscordConfig.objects.create(notify_taken=False)

        with patch.object(app_settings, "EVEBUILDERS_DISCORD_NOTIFY_TAKEN", True):
            self.assertFalse(notify_taken_enabled())

        config.notify_taken = True
        config.save()

        with patch.object(app_settings, "EVEBUILDERS_DISCORD_NOTIFY_TAKEN", False):
            self.assertTrue(notify_taken_enabled())


@override_settings(STORAGES=TEST_STORAGES)
class TestDiscordConfigAdmin(TestCase):
    """The page in the Django admin"""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.admin_user = User.objects.create_superuser(
            "root", "root@example.com", "password"
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin_user)

    @staticmethod
    def _data(**overrides):
        data = {
            "new_order_webhook_url": "https://discord.com/api/webhooks/1/abc",
            "new_order_thread_id": "",
            "complete_webhook_url": "https://discord.com/api/webhooks/2/xyz",
            "complete_thread_id": "",
            "notify_taken": "unknown",
        }
        data.update(overrides)

        return data

    def _add(self, **overrides):
        return self.client.post(
            reverse("admin:evebuilders_discordconfig_add"), self._data(**overrides)
        )

    def test_the_page_is_there(self):
        response = self.client.get(reverse("admin:evebuilders_discordconfig_add"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Channel for new orders")

    def test_the_settings_can_be_saved(self):
        response = self._add(new_order_thread_id="123", notify_taken="false")

        self.assertEqual(response.status_code, 302)
        config = DiscordConfig.objects.get()
        self.assertEqual(config.new_order_thread_id, "123")
        self.assertIs(config.notify_taken, False)

    def test_a_url_must_be_https(self):
        response = self._add(new_order_webhook_url="http://discord.com/api/webhooks/1/a")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "must start with https://")
        self.assertFalse(DiscordConfig.objects.exists())

    def test_a_thread_id_must_be_a_number(self):
        response = self._add(complete_thread_id="abc")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A thread ID is a number")
        self.assertFalse(DiscordConfig.objects.exists())

    def test_only_one_row_can_be_added(self):
        self._add()

        response = self.client.get(reverse("admin:evebuilders_discordconfig_add"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(DiscordConfig.objects.count(), 1)

    def test_the_row_cannot_be_deleted(self):
        self._add()
        config = DiscordConfig.objects.get()

        response = self.client.post(
            reverse("admin:evebuilders_discordconfig_delete", args=[config.pk]),
            {"post": "yes"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(DiscordConfig.objects.exists())