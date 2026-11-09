"""Discord notifications: formatting and delivery (Discord is mocked out)"""

# Standard Library
from decimal import Decimal
from unittest.mock import MagicMock, patch

# Third Party
import requests

# Django
from django.test import SimpleTestCase, TestCase

# AA EVE Builders
from evebuilders import app_settings
from evebuilders.notifications import (
    CHANNEL_COMPLETE,
    CHANNEL_NEW_ORDER,
    DiscordRetry,
    build_payload,
    deliver,
    format_isk,
    isk_in_words,
    notify,
    positions_for,
    positions_of,
    retry_delay,
)
from evebuilders.tasks import send_discord_notification

POST = "evebuilders.notifications.requests.post"
URL = "https://discord.com/api/webhooks/1/abc"
OTHER_URL = "https://discord.com/api/webhooks/2/xyz"


def fake_response(status=204, headers=None, json_data=None, text=""):
    """A stand-in for a requests response"""

    response = MagicMock()
    response.status_code = status
    response.headers = headers or {}
    response.text = text
    if json_data is None:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = json_data

    return response


class SettingsMixin:
    """Set the Discord settings for one test"""

    def configure(self, **settings):
        for name, value in settings.items():
            patcher = patch.object(app_settings, f"EVEBUILDERS_DISCORD_{name}", value)
            patcher.start()
            self.addCleanup(patcher.stop)


class TestFormatIsk(SimpleTestCase):
    """format_isk"""

    def test_groups_with_spaces_and_no_decimals(self):
        self.assertEqual(format_isk(Decimal("1000000")), "1 000 000 ISK")
        self.assertEqual(format_isk(Decimal("100")), "100 ISK")
        self.assertEqual(format_isk(Decimal("0.5")), "1 ISK")
        self.assertEqual(format_isk(Decimal("1234.567")), "1 235 ISK")

    def test_accepts_numbers_that_are_not_decimals(self):
        self.assertEqual(format_isk(250), "250 ISK")
        self.assertEqual(format_isk(100.0), "100 ISK")

    def test_nothing_gives_an_empty_text(self):
        self.assertEqual(format_isk(None), "")


class TestIskInWords(SimpleTestCase):
    """isk_in_words"""

    def _check(self, cases):
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(isk_in_words(Decimal(value)), expected)

    def test_millions(self):
        self._check(
            {
                "275000000": "275 миллионов",
                "21000000": "21 миллион",
                "22000000": "22 миллиона",
                "11000000": "11 миллионов",
                "1000000": "1 миллион",
                "5000000": "5 миллионов",
            }
        )

    def test_fractions_use_the_genitive_singular(self):
        self._check({"1500000": "1,5 миллиона", "2500000000": "2,5 миллиарда"})

    def test_billions(self):
        self._check(
            {
                "1000000000": "1 миллиард",
                "3000000000": "3 миллиарда",
                "7000000000": "7 миллиардов",
            }
        )

    def test_it_cuts_instead_of_rounding(self):
        self._check({"1999999": "1,9 миллиона"})

    def test_amounts_below_a_million_have_no_words(self):
        self._check({"999999": "", "5000": "", "1000": "", "100": "", "0": ""})

    def test_nothing_gives_no_words(self):
        self.assertEqual(isk_in_words(None), "")


class TestPositions(SimpleTestCase):
    """positions_for and positions_of"""

    def test_after_na(self):
        cases = {
            1: "1 позицию",
            2: "2 позиции",
            4: "4 позиции",
            5: "5 позиций",
            11: "11 позиций",
            21: "21 позицию",
            22: "22 позиции",
            100: "100 позиций",
            101: "101 позицию",
        }
        for count, expected in cases.items():
            with self.subTest(count=count):
                self.assertEqual(positions_for(count), expected)

    def test_after_ot(self):
        cases = {
            1: "1 позиции",
            2: "2 позиций",
            5: "5 позиций",
            11: "11 позиций",
            21: "21 позиции",
            22: "22 позиций",
        }
        for count, expected in cases.items():
            with self.subTest(count=count):
                self.assertEqual(positions_of(count), expected)


class TestBuildPayload(SimpleTestCase):
    """build_payload"""

    def test_shape(self):
        payload = build_payload(
            ["Отчет от - Ivan"],
            [("Заказ", "N20261027-1"), ("Наименование", "Punisher")],
        )

        self.assertEqual(payload["content"], "@everyone")
        self.assertEqual(payload["allowed_mentions"], {"parse": ["everyone"]})
        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "EVE Builders Notification")
        self.assertEqual(embed["color"], 0x2B6CB0)
        self.assertEqual(embed["description"], "Отчет от - Ivan")
        self.assertEqual(
            embed["fields"],
            [
                {"name": "Заказ", "value": "N20261027-1", "inline": False},
                {"name": "Наименование", "value": "Punisher", "inline": False},
            ],
        )

    def test_empty_parts_are_left_out(self):
        nothing = build_payload()["embeds"][0]
        empty_value = build_payload(["x"], [("Поле", "")])["embeds"][0]

        self.assertNotIn("description", nothing)
        self.assertNotIn("fields", nothing)
        self.assertEqual(empty_value["description"], "x")
        self.assertNotIn("fields", empty_value)

    def test_description_lines_are_joined(self):
        embed = build_payload(["first", "", "second"])["embeds"][0]

        self.assertEqual(embed["description"], "first\nsecond")

    def test_long_texts_are_cut_to_the_discord_limits(self):
        embed = build_payload(["d" * 5000], [("n" * 300, "v" * 2000)])["embeds"][0]

        self.assertEqual(len(embed["description"]), 4096)
        self.assertTrue(embed["description"].endswith("..."))
        self.assertEqual(len(embed["fields"][0]["name"]), 256)
        self.assertEqual(len(embed["fields"][0]["value"]), 1024)

    def test_at_most_25_fields(self):
        fields = [(f"name {i}", f"value {i}") for i in range(30)]

        embed = build_payload(fields=fields)["embeds"][0]

        self.assertEqual(len(embed["fields"]), 25)

    def test_spaces_at_the_end_are_removed(self):
        embed = build_payload(
            ["Контракт 100,00 ISK "], [("Цена", "100,00 ISK "), ("Пусто", "  ")]
        )["embeds"][0]

        self.assertEqual(embed["description"], "Контракт 100,00 ISK")
        self.assertEqual(
            embed["fields"], [{"name": "Цена", "value": "100,00 ISK", "inline": False}]
        )


class TestDeliver(SettingsMixin, TestCase):
    """deliver"""

    PAYLOAD = {"content": "@everyone"}

    @patch(POST)
    def test_no_webhook_means_nothing_is_sent(self, mock_post):
        self.configure(COMPLETE_WEBHOOK_URL="")

        self.assertEqual(deliver(CHANNEL_COMPLETE, self.PAYLOAD), "skipped")
        mock_post.assert_not_called()

    @patch(POST, return_value=fake_response(204))
    def test_sends_the_payload(self, mock_post):
        self.configure(COMPLETE_WEBHOOK_URL=URL, COMPLETE_THREAD_ID="")

        self.assertEqual(deliver(CHANNEL_COMPLETE, self.PAYLOAD), "sent")

        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], URL)
        self.assertEqual(kwargs["json"], self.PAYLOAD)
        self.assertIsNone(kwargs["params"])
        self.assertIn("aa-eve-builders", kwargs["headers"]["User-Agent"])

    @patch(POST, return_value=fake_response(204))
    def test_a_thread_id_is_sent_as_a_parameter(self, mock_post):
        self.configure(COMPLETE_WEBHOOK_URL=URL, COMPLETE_THREAD_ID="123")

        deliver(CHANNEL_COMPLETE, self.PAYLOAD)

        self.assertEqual(mock_post.call_args.kwargs["params"], {"thread_id": "123"})

    @patch(POST, return_value=fake_response(204))
    def test_every_channel_has_its_own_webhook(self, mock_post):
        self.configure(
            NEW_ORDER_WEBHOOK_URL=OTHER_URL,
            NEW_ORDER_THREAD_ID="",
            COMPLETE_WEBHOOK_URL=URL,
            COMPLETE_THREAD_ID="",
        )

        deliver(CHANNEL_NEW_ORDER, self.PAYLOAD)

        self.assertEqual(mock_post.call_args.args[0], OTHER_URL)

    @patch(POST)
    def test_the_rate_limit_asks_to_wait(self, mock_post):
        self.configure(COMPLETE_WEBHOOK_URL=URL, COMPLETE_THREAD_ID="")
        cases = {
            "header": fake_response(429, headers={"Retry-After": "2"}),
            "body": fake_response(429, json_data={"retry_after": 1.5}),
        }
        expected = {"header": 2.0, "body": 1.5}

        for name, response in cases.items():
            with self.subTest(name=name):
                mock_post.return_value = response

                with self.assertRaises(DiscordRetry) as caught:
                    deliver(CHANNEL_COMPLETE, self.PAYLOAD)

                self.assertEqual(caught.exception.retry_after, expected[name])

    @patch(POST)
    def test_server_trouble_is_worth_a_retry(self, mock_post):
        self.configure(COMPLETE_WEBHOOK_URL=URL, COMPLETE_THREAD_ID="")

        for status in (500, 502, 503):
            with self.subTest(status=status):
                mock_post.return_value = fake_response(status)

                with self.assertRaises(DiscordRetry) as caught:
                    deliver(CHANNEL_COMPLETE, self.PAYLOAD)

                self.assertIsNone(caught.exception.retry_after)

    @patch(POST)
    def test_a_refusal_is_final(self, mock_post):
        self.configure(COMPLETE_WEBHOOK_URL=URL, COMPLETE_THREAD_ID="")

        for status in (400, 401, 404):
            with self.subTest(status=status):
                mock_post.return_value = fake_response(status, text="bad")

                self.assertEqual(deliver(CHANNEL_COMPLETE, self.PAYLOAD), "rejected")

    @patch(POST, side_effect=requests.ConnectionError("no network"))
    def test_a_network_problem_is_worth_a_retry(self, _mock_post):
        self.configure(COMPLETE_WEBHOOK_URL=URL, COMPLETE_THREAD_ID="")

        with self.assertRaises(DiscordRetry):
            deliver(CHANNEL_COMPLETE, self.PAYLOAD)

    def test_unknown_channel(self):
        with self.assertRaises(ValueError):
            deliver("nonsense", self.PAYLOAD)


class TestRetryDelay(SimpleTestCase):
    """retry_delay"""

    def test_grows_and_is_capped(self):
        self.assertEqual(retry_delay(0), 30)
        self.assertEqual(retry_delay(1), 60)
        self.assertEqual(retry_delay(5), 900)

    def test_follows_what_discord_asks(self):
        self.assertEqual(retry_delay(0, retry_after=2.0), 3)
        self.assertEqual(retry_delay(0, retry_after=0.2), 2)


class TestNotify(SettingsMixin, TestCase):
    """notify"""

    TASK = "evebuilders.tasks.send_discord_notification.delay"

    def test_nothing_is_queued_without_a_webhook(self):
        self.configure(COMPLETE_WEBHOOK_URL="", COMPLETE_THREAD_ID="")

        with patch(self.TASK) as delay:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                notify(CHANNEL_COMPLETE, {"a": 1})

        self.assertEqual(callbacks, [])
        delay.assert_not_called()

    def test_the_message_is_queued_only_after_the_commit(self):
        self.configure(COMPLETE_WEBHOOK_URL=URL, COMPLETE_THREAD_ID="")

        with patch(self.TASK) as delay:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                notify(CHANNEL_COMPLETE, {"a": 1})

            delay.assert_not_called()
            self.assertEqual(len(callbacks), 1)

            callbacks[0]()

            delay.assert_called_once_with(CHANNEL_COMPLETE, {"a": 1})

    def test_other_channels_are_not_affected(self):
        self.configure(
            NEW_ORDER_WEBHOOK_URL=OTHER_URL,
            NEW_ORDER_THREAD_ID="",
            COMPLETE_WEBHOOK_URL="",
            COMPLETE_THREAD_ID="",
        )

        with patch(self.TASK) as delay:
            with self.captureOnCommitCallbacks(execute=True):
                notify(CHANNEL_COMPLETE, {"a": 1})

        delay.assert_not_called()


class TestSendDiscordNotificationTask(SimpleTestCase):
    """The Celery task"""

    @patch("evebuilders.tasks.deliver", return_value="sent")
    def test_returns_what_was_done(self, mock_deliver):
        result = send_discord_notification.run(CHANNEL_COMPLETE, {"a": 1})

        self.assertEqual(result, "sent")
        mock_deliver.assert_called_once_with(CHANNEL_COMPLETE, {"a": 1})

    @patch("evebuilders.tasks.deliver", side_effect=DiscordRetry("busy", 2.0))
    def test_tries_again_when_discord_is_busy(self, _mock_deliver):
        with patch.object(
            send_discord_notification, "retry", side_effect=RuntimeError("retry")
        ) as retry:
            with self.assertRaises(RuntimeError):
                send_discord_notification.run(CHANNEL_COMPLETE, {"a": 1})

        retry.assert_called_once()
        self.assertEqual(retry.call_args.kwargs["countdown"], 3)
