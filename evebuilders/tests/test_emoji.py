"""The emoji at the start of the Discord messages"""

# Django
from django.test import SimpleTestCase

# AA EVE Builders
from evebuilders import messages
from evebuilders.manager_actions import Change
from evebuilders.notifications import (
    EMOJI_CHANGED,
    EMOJI_CREDITED_BY_HAND,
    EMOJI_DELETED,
    EMOJI_GIVEN_BACK,
    EMOJI_NEW,
    EMOJI_TAKEN,
    add_emoji,
    build_payload,
    with_emoji,
)
from evebuilders.tests.test_take_discard_views import ViewsTestCase

EVERY_MESSAGE = (
    "new_order_payload",
    "order_changed_payload",
    "order_cancelled_payload",
    "taken_payload",
    "discard_payload",
    "released_payload",
    "contract_waiting_payload",
    "contract_credited_payload",
    "manual_credit_payload",
    "contract_invalid_payload",
    "token_failure_payload",
)


class TestAddEmoji(SimpleTestCase):
    """add_emoji and with_emoji"""

    def test_it_goes_before_the_first_line(self):
        payload = add_emoji(build_payload(["first", "second"]), "X")

        self.assertEqual(payload["embeds"][0]["description"], "X first\nsecond")

    def test_without_a_text_it_goes_before_the_title(self):
        payload = add_emoji(build_payload(), "X")

        self.assertEqual(payload["embeds"][0]["title"], "X PROB Builders Notification")

    def test_the_decorator_keeps_the_function_and_adds_the_emoji(self):
        @with_emoji("X")
        def make():
            """A message"""

            return build_payload(["line"])

        self.assertEqual(make()["embeds"][0]["description"], "X line")
        self.assertEqual(make.__name__, "make")

    def test_every_message_of_the_plugin_has_an_emoji(self):
        for name in EVERY_MESSAGE:
            with self.subTest(message=name):
                self.assertTrue(hasattr(getattr(messages, name), "__wrapped__"))


class TestMessagesStartWithTheirEmoji(ViewsTestCase):
    """What the real messages look like"""

    @staticmethod
    def _text(payload):
        return payload["embeds"][0]["description"]

    def test_a_new_order(self):
        payload = messages.new_order_payload(self.order)

        # This message has no lines of text, only fields: the emoji goes before the title
        self.assertTrue(payload["embeds"][0]["title"].startswith(f"{EMOJI_NEW} "))

    def test_an_order_taken(self):
        payload = messages.taken_payload(
            user=self.builder, order=self.order, quantity=5, free=995
        )

        self.assertTrue(self._text(payload).startswith(f"{EMOJI_TAKEN} "))

    def test_an_order_changed(self):
        payload = messages.order_changed_payload(
            manager=self.manager,
            order=self.order,
            changes=[Change("quantity", 1000, 1200)],
        )

        self.assertTrue(self._text(payload).startswith(f"{EMOJI_CHANGED} "))

    def test_an_order_deleted(self):
        payload = messages.order_cancelled_payload(
            manager=self.manager, order=self.order, taken=0
        )

        self.assertTrue(self._text(payload).startswith(f"{EMOJI_DELETED} "))

    def test_a_share_released(self):
        payload = messages.released_payload(
            manager=self.manager,
            builder=self.builder,
            order=self.order,
            quantity=5,
            free=10,
        )

        self.assertTrue(self._text(payload).startswith(f"{EMOJI_GIVEN_BACK} "))

    def test_credited_by_hand(self):
        payload = messages.manual_credit_payload(
            manager=self.manager,
            builder=self.builder,
            order=self.order,
            quantity=5,
            remaining=10,
        )

        self.assertTrue(self._text(payload).startswith(f"{EMOJI_CREDITED_BY_HAND} "))
