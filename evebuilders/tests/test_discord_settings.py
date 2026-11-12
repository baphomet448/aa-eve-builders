"""The tab Discord of the settings: the channels and where each kind goes"""

# Standard Library
from unittest.mock import patch

# Django
from django.contrib.messages import get_messages
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders import app_settings
from evebuilders.discord_settings import is_discord_webhook
from evebuilders.models import DiscordConfig
from evebuilders.notifications import (
    CHANNEL_COMPLETE,
    CHANNEL_NEW_ORDER,
    CHANNEL_REVIEW,
    CHANNELS,
    DEFAULT_CHANNELS,
    KIND_NEW_ORDER,
    KIND_TAKEN,
    route_of,
)
from evebuilders.tests.test_notifications import fake_response
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES

URL = "https://discord.com/api/webhooks/123/secret-token-abcdef"
POST = "evebuilders.notifications.requests.post"


class TestIsDiscordWebhook(SimpleTestCase):
    """Only the addresses of Discord are taken"""

    def test_the_addresses_of_discord(self):
        for url in (
            URL,
            "https://discordapp.com/api/webhooks/1/x",
            "https://canary.discord.com/api/webhooks/1/x",
        ):
            with self.subTest(url=url):
                self.assertTrue(is_discord_webhook(url))

    def test_other_addresses(self):
        for url in (
            "http://discord.com/api/webhooks/1/x",
            "https://evil.example/api/webhooks/1/x",
            "https://discord.com.evil.example/api/webhooks/1/x",
            "https://discord.com@evil.example/api/webhooks/1/x",
            "https://discord.com/other/path",
            "not an address",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_discord_webhook(url))


@override_settings(STORAGES=TEST_STORAGES)
class DiscordSettingsTestCase(ViewsTestCase):
    """Helpers for the pages"""

    def setUp(self):
        DiscordConfig.objects.all().delete()

    @staticmethod
    def _data(**overrides):
        data = {}
        for channel in CHANNELS:
            data[f"url_{channel}"] = ""
            data[f"thread_{channel}"] = ""
        for kind, channel in DEFAULT_CHANNELS.items():
            data[f"route_{kind}"] = channel
            data[f"everyone_{kind}"] = "on"
        data.update(overrides)

        return data

    def _get(self, user=None):
        self.client.force_login(user or self.manager)

        return self.client.get(reverse("evebuilders:discord_settings"))

    def _post(self, **overrides):
        self.client.force_login(self.manager)

        return self.client.post(
            reverse("evebuilders:discord_settings"), self._data(**overrides)
        )

    def _action(self, action):
        self.client.force_login(self.manager)

        return self.client.post(
            reverse("evebuilders:discord_settings"), {"action": action}
        )

    @staticmethod
    def _messages(response):
        return [str(message) for message in get_messages(response.wsgi_request)]


class TestTheTab(DiscordSettingsTestCase):
    """Access and the page"""

    def test_only_managers_get_in(self):
        url = reverse("evebuilders:discord_settings")

        self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(self._get(self.builder).status_code, 302)
        self.assertEqual(self._get(self.manager).status_code, 200)

    def test_the_tab_is_in_the_strip_of_the_settings(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:settings"))

        self.assertContains(response, reverse("evebuilders:discord_settings"))

    def test_the_page_never_shows_a_webhook_address(self):
        DiscordConfig.objects.create(new_order_webhook_url=URL)

        response = self._get()

        self.assertNotContains(response, URL)
        self.assertContains(response, "abcdef")
        self.assertContains(response, "Set")

    def test_a_webhook_from_local_py_is_marked(self):
        with patch.object(
            app_settings, "EVEBUILDERS_DISCORD_COMPLETE_WEBHOOK_URL", URL
        ):
            response = self._get()

        self.assertNotContains(response, URL)
        self.assertContains(response, "From local.py")

    def test_the_three_channels_have_their_names(self):
        response = self._get()

        for name in ("New orders", "On review", "Everything else"):
            with self.subTest(name=name):
                self.assertContains(response, name)

    def test_every_kind_has_a_row(self):
        response = self._get()

        for text in ("New order", "Credited by hand", "The ESI token stopped working"):
            with self.subTest(text=text):
                self.assertContains(response, text)
        self.assertContains(response, 'name="route_taken"')
        self.assertContains(response, 'name="everyone_token_failure"')


class TestSavingTheChannels(DiscordSettingsTestCase):
    """The webhooks and the threads"""

    def test_a_new_address_is_saved(self):
        response = self._post(**{f"url_{CHANNEL_REVIEW}": URL})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(DiscordConfig.objects.get().review_webhook_url, URL)
        self.assertIn("The Discord settings were saved.", self._messages(response))

    def test_an_empty_field_keeps_the_saved_address(self):
        DiscordConfig.objects.create(new_order_webhook_url=URL)

        self._post()

        self.assertEqual(DiscordConfig.objects.get().new_order_webhook_url, URL)

    def test_a_webhook_is_removed_on_request(self):
        DiscordConfig.objects.create(complete_webhook_url=URL, complete_thread_id="55")

        self._post(**{f"clear_{CHANNEL_COMPLETE}": "on"})

        config = DiscordConfig.objects.get()
        self.assertEqual(config.complete_webhook_url, "")
        self.assertEqual(config.complete_thread_id, "")

    def test_the_thread_is_saved(self):
        self._post(**{f"thread_{CHANNEL_NEW_ORDER}": "12345"})

        self.assertEqual(DiscordConfig.objects.get().new_order_thread_id, "12345")

    def test_a_thread_that_is_not_a_number_is_refused(self):
        response = self._post(**{f"thread_{CHANNEL_NEW_ORDER}": "abc"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The thread ID is a number.")
        self.assertFalse(DiscordConfig.objects.exists())

    def test_an_address_that_is_not_discord_is_refused(self):
        response = self._post(
            **{f"url_{CHANNEL_NEW_ORDER}": "https://evil.example/api/webhooks/1/x"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The address must be a Discord webhook")
        self.assertFalse(DiscordConfig.objects.exists())


class TestSavingTheRoutes(DiscordSettingsTestCase):
    """Where each kind goes"""

    def test_a_route_and_the_mention_are_saved(self):
        # The mention of the kind is left out of the form: it is switched off
        data = self._data(**{f"route_{KIND_TAKEN}": CHANNEL_REVIEW})
        del data[f"everyone_{KIND_TAKEN}"]
        self.client.force_login(self.manager)

        self.client.post(reverse("evebuilders:discord_settings"), data)

        self.assertEqual(route_of(KIND_TAKEN), (CHANNEL_REVIEW, False))
        self.assertEqual(route_of(KIND_NEW_ORDER), (CHANNEL_NEW_ORDER, True))
        self.assertEqual(len(DiscordConfig.objects.get().routes), 11)

    def test_a_kind_can_be_switched_off(self):
        self._post(**{f"route_{KIND_NEW_ORDER}": ""})

        self.assertEqual(route_of(KIND_NEW_ORDER), ("", True))

    def test_the_page_shows_the_saved_route(self):
        DiscordConfig.objects.create(
            routes={KIND_TAKEN: {"channel": CHANNEL_REVIEW, "everyone": True}}
        )

        response = self._get()

        self.assertContains(response, 'value="review" selected')

    def test_reset_brings_back_the_defaults(self):
        DiscordConfig.objects.create(
            routes={KIND_TAKEN: {"channel": CHANNEL_REVIEW, "everyone": False}}
        )

        response = self._action("reset_routes")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(DiscordConfig.objects.get().routes, {})
        self.assertEqual(route_of(KIND_TAKEN), (CHANNEL_COMPLETE, True))

    def test_messages_to_a_channel_without_a_webhook_are_warned_about(self):
        DiscordConfig.objects.create(
            routes={KIND_TAKEN: {"channel": CHANNEL_REVIEW, "everyone": True}}
        )

        response = self._get()

        self.assertContains(response, "These messages are not sent")
        self.assertContains(response, "A builder took a part")


class TestTheTestMessage(DiscordSettingsTestCase):
    """The button that sends a test message"""

    def _test(self, channel):
        self.client.force_login(self.manager)

        return self.client.post(
            reverse("evebuilders:discord_test"), {"channel": channel}
        )

    def test_a_builder_is_sent_away(self):
        self.client.force_login(self.builder)

        with patch(POST) as post:
            response = self.client.post(
                reverse("evebuilders:discord_test"), {"channel": CHANNEL_NEW_ORDER}
            )

        post.assert_not_called()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/account/login/"))

    def test_a_test_message_is_sent_without_the_mention(self):
        DiscordConfig.objects.create(new_order_webhook_url=URL)

        with patch(POST, return_value=fake_response(204)) as post:
            response = self._test(CHANNEL_NEW_ORDER)

        post.assert_called_once()
        sent = post.call_args.kwargs["json"]
        self.assertNotIn("content", sent)
        self.assertNotIn("allowed_mentions", sent)
        self.assertIn(
            'A test message was sent to the channel "New orders".',
            self._messages(response),
        )

    def test_a_channel_without_a_webhook_sends_nothing(self):
        with patch(POST) as post:
            response = self._test(CHANNEL_REVIEW)

        post.assert_not_called()
        self.assertIn(
            'The channel "On review" has no webhook.', self._messages(response)
        )

    def test_a_refused_message_is_reported(self):
        DiscordConfig.objects.create(new_order_webhook_url=URL)

        with patch(POST, return_value=fake_response(400)):
            response = self._test(CHANNEL_NEW_ORDER)

        self.assertIn(
            "Discord refused the message. Check the webhook address and the "
            "thread ID.",
            self._messages(response),
        )

    def test_an_unknown_channel_is_refused(self):
        with patch(POST) as post:
            response = self._test("nowhere")

        post.assert_not_called()
        self.assertIn("Unknown channel.", self._messages(response))
