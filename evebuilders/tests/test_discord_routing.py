"""Where the Discord messages go: the routing of the kinds of messages"""

# Standard Library
from unittest.mock import patch

# Django
from django.test import SimpleTestCase, TestCase

# AA EVE Builders
from evebuilders import messages
from evebuilders.manager_actions import Change
from evebuilders.models import DiscordConfig
from evebuilders.notifications import (
    CHANNEL_COMPLETE,
    CHANNEL_NEW_ORDER,
    CHANNEL_PROBLEMS,
    DEFAULT_CHANNELS,
    KIND_CONTRACT_INVALID,
    KIND_KEY,
    KIND_NEW_ORDER,
    KIND_ORDER_CANCELLED,
    KIND_ORDER_CHANGED,
    KIND_RELEASED,
    KIND_TAKEN,
    _webhook,
    build_payload,
    message_of,
    notify,
    route_of,
    without_everyone,
)
from evebuilders.tests.test_take_discard_views import ViewsTestCase

NEW_ORDER_URL = "https://discord.com/api/webhooks/1/new"
COMPLETE_URL = "https://discord.com/api/webhooks/2/complete"
PROBLEMS_URL = "https://discord.com/api/webhooks/3/problems"
DELAY = "evebuilders.tasks.send_discord_notification.delay"


class TestDefaults(TestCase):
    """Nothing set: the two channels as they were before"""

    def test_every_kind_has_a_default_channel(self):
        self.assertEqual(len(DEFAULT_CHANNELS), 11)

    def test_three_kinds_go_to_the_new_orders_and_eight_to_the_reports(self):
        channels = list(DEFAULT_CHANNELS.values())

        self.assertEqual(channels.count(CHANNEL_NEW_ORDER), 3)
        self.assertEqual(channels.count(CHANNEL_COMPLETE), 8)

    def test_the_default_route_mentions_everyone(self):
        for kind, channel in DEFAULT_CHANNELS.items():
            with self.subTest(kind=kind):
                self.assertEqual(route_of(kind), (channel, True))


class TestSavedRoutes(TestCase):
    """What the settings of the plugin say"""

    def _save(self, **routes):
        DiscordConfig.objects.all().delete()

        return DiscordConfig.objects.create(routes=routes)

    def test_a_saved_route_wins(self):
        self._save(**{KIND_TAKEN: {"channel": CHANNEL_PROBLEMS, "everyone": False}})

        self.assertEqual(route_of(KIND_TAKEN), (CHANNEL_PROBLEMS, False))

    def test_a_kind_can_be_switched_off(self):
        self._save(**{KIND_NEW_ORDER: {"channel": "", "everyone": True}})

        self.assertEqual(route_of(KIND_NEW_ORDER), ("", True))

    def test_an_unknown_channel_is_ignored(self):
        self._save(**{KIND_TAKEN: {"channel": "nowhere", "everyone": False}})

        self.assertEqual(route_of(KIND_TAKEN), (CHANNEL_COMPLETE, False))

    def test_the_mention_is_on_when_a_route_does_not_say(self):
        self._save(**{KIND_TAKEN: {"channel": CHANNEL_PROBLEMS}})

        self.assertEqual(route_of(KIND_TAKEN), (CHANNEL_PROBLEMS, True))

    def test_the_older_switch_for_taken_still_works(self):
        DiscordConfig.objects.create(notify_taken=False)

        self.assertEqual(route_of(KIND_TAKEN), ("", True))
        self.assertEqual(route_of(KIND_NEW_ORDER), (CHANNEL_NEW_ORDER, True))

    def test_a_saved_route_wins_over_the_older_switch(self):
        DiscordConfig.objects.create(
            notify_taken=False,
            routes={KIND_TAKEN: {"channel": CHANNEL_PROBLEMS, "everyone": True}},
        )

        self.assertEqual(route_of(KIND_TAKEN), (CHANNEL_PROBLEMS, True))


class TestThirdChannel(TestCase):
    """The webhook of the third channel"""

    def test_it_comes_from_the_settings_of_the_plugin(self):
        DiscordConfig.objects.create(
            problems_webhook_url=PROBLEMS_URL, problems_thread_id="123"
        )

        self.assertEqual(_webhook(CHANNEL_PROBLEMS), (PROBLEMS_URL, "123"))

    def test_without_settings_it_is_empty(self):
        self.assertEqual(_webhook(CHANNEL_PROBLEMS), ("", ""))


class TestPayload(SimpleTestCase):
    """The mention and the kind of a message"""

    def test_a_message_mentions_everyone_by_default(self):
        payload = build_payload(["text"])

        self.assertEqual(payload["content"], "@everyone")
        self.assertEqual(payload["allowed_mentions"], {"parse": ["everyone"]})

    def test_a_message_can_be_quiet(self):
        payload = build_payload(["text"], mention=False)

        self.assertNotIn("content", payload)
        self.assertNotIn("allowed_mentions", payload)
        self.assertEqual(len(payload["embeds"]), 1)

    def test_without_everyone_keeps_the_rest(self):
        quiet = without_everyone(build_payload(["text"]))

        self.assertEqual(quiet, build_payload(["text"], mention=False))

    def test_a_message_of_a_kind_has_its_emoji_and_its_kind(self):
        @message_of("something", "X")
        def make():
            """A message"""

            return build_payload(["line"])

        payload = make()

        self.assertEqual(payload["embeds"][0]["description"], "X line")
        self.assertEqual(payload[KIND_KEY], "something")
        self.assertEqual(make.__name__, "make")


class TestNotifyUsesTheRoute(TestCase):
    """notify sends a message where its kind goes"""

    def setUp(self):
        self.config = DiscordConfig.objects.create(
            new_order_webhook_url=NEW_ORDER_URL,
            complete_webhook_url=COMPLETE_URL,
            problems_webhook_url=PROBLEMS_URL,
        )

    @staticmethod
    def _kind_message(kind):
        payload = build_payload(["text"])
        payload[KIND_KEY] = kind

        return payload

    def _notify(self, channel, payload):
        with patch(DELAY) as delay, self.captureOnCommitCallbacks(execute=True):
            notify(channel, payload)

        return delay

    def test_a_message_without_a_kind_goes_to_the_given_channel(self):
        payload = build_payload(["text"])

        delay = self._notify(CHANNEL_COMPLETE, payload)

        delay.assert_called_once_with(CHANNEL_COMPLETE, payload)

    def test_a_message_goes_to_the_channel_of_its_kind(self):
        self.config.routes = {KIND_TAKEN: {"channel": CHANNEL_PROBLEMS}}
        self.config.save()

        delay = self._notify(CHANNEL_COMPLETE, self._kind_message(KIND_TAKEN))

        channel, sent = delay.call_args.args
        self.assertEqual(channel, CHANNEL_PROBLEMS)
        self.assertNotIn(KIND_KEY, sent)
        self.assertEqual(sent["content"], "@everyone")

    def test_the_default_channel_is_used_when_nothing_is_saved(self):
        delay = self._notify(
            CHANNEL_NEW_ORDER, self._kind_message(KIND_CONTRACT_INVALID)
        )

        self.assertEqual(delay.call_args.args[0], CHANNEL_COMPLETE)

    def test_a_message_can_go_without_the_mention(self):
        self.config.routes = {
            KIND_NEW_ORDER: {"channel": CHANNEL_NEW_ORDER, "everyone": False}
        }
        self.config.save()

        delay = self._notify(CHANNEL_NEW_ORDER, self._kind_message(KIND_NEW_ORDER))

        sent = delay.call_args.args[1]
        self.assertNotIn("content", sent)
        self.assertNotIn("allowed_mentions", sent)

    def test_a_kind_that_is_switched_off_sends_nothing(self):
        self.config.routes = {KIND_RELEASED: {"channel": "", "everyone": True}}
        self.config.save()

        delay = self._notify(CHANNEL_COMPLETE, self._kind_message(KIND_RELEASED))

        delay.assert_not_called()

    def test_a_channel_without_a_webhook_sends_nothing(self):
        self.config.problems_webhook_url = ""
        self.config.routes = {KIND_TAKEN: {"channel": CHANNEL_PROBLEMS}}
        self.config.save()

        delay = self._notify(CHANNEL_COMPLETE, self._kind_message(KIND_TAKEN))

        delay.assert_not_called()


class TestMessagesKnowTheirKind(ViewsTestCase):
    """The real messages carry their kind"""

    def test_the_kinds(self):
        cases = [
            (messages.new_order_payload(self.order), KIND_NEW_ORDER),
            (
                messages.order_changed_payload(
                    manager=self.manager,
                    order=self.order,
                    changes=[Change("quantity", 1000, 1200)],
                ),
                KIND_ORDER_CHANGED,
            ),
            (
                messages.order_cancelled_payload(
                    manager=self.manager, order=self.order, taken=0
                ),
                KIND_ORDER_CANCELLED,
            ),
            (
                messages.taken_payload(
                    user=self.builder, order=self.order, quantity=5, free=995
                ),
                KIND_TAKEN,
            ),
            (
                messages.released_payload(
                    manager=self.manager,
                    builder=self.builder,
                    order=self.order,
                    quantity=5,
                    free=10,
                ),
                KIND_RELEASED,
            ),
        ]

        for payload, kind in cases:
            with self.subTest(kind=kind):
                self.assertEqual(payload[KIND_KEY], kind)
