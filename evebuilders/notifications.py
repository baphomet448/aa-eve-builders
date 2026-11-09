"""Discord notifications: message formatting and delivery through webhooks"""

# Standard Library
import functools
import logging
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from math import ceil

# Third Party
import requests

# Django
from django.db import transaction

# AA EVE Builders
from evebuilders import __version__, app_settings
from evebuilders.models import DiscordConfig

logger = logging.getLogger(__name__)

# The two channels (webhooks), named after the channels of the live system
CHANNEL_NEW_ORDER = "new_order"  # industry-new-order-ping
CHANNEL_COMPLETE = "complete"  # industry-complete-ping

EMBED_TITLE = "EVE Builders Notification"
EMBED_COLOR = 0x2B6CB0
EVERYONE_MENTION = "@everyone"

# Discord limits
TITLE_LIMIT = 256
DESCRIPTION_LIMIT = 4096
FIELD_NAME_LIMIT = 256
FIELD_VALUE_LIMIT = 1024
MAX_FIELDS = 25

DISCORD_TIMEOUT = 15  # seconds

_BILLION = Decimal(10**9)
_MILLION = Decimal(10**6)
_SCALES = (
    (_BILLION, ("миллиард", "миллиарда", "миллиардов")),
    (_MILLION, ("миллион", "миллиона", "миллионов")),
)


class DiscordRetry(Exception):
    """Discord did not take the message now, but it is worth trying again"""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def format_isk(value) -> str:
    """An amount in whole ISK: 1 000 000 ISK"""

    if value is None:
        return ""

    amount = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    return f"{amount:,.0f}".replace(",", " ") + " ISK"


def _number_text(amount: Decimal) -> str:
    """A number with at most one decimal, cut (not rounded), with a decimal comma"""

    amount = amount.quantize(Decimal("0.1"), rounding=ROUND_DOWN)
    if amount == amount.to_integral_value():
        return str(int(amount))

    return str(amount).replace(".", ",")


def _plural(amount: Decimal, one: str, few: str, many: str) -> str:
    """The Russian word form for a number: 1 миллион, 2 миллиона, 5 миллионов"""

    if amount != amount.to_integral_value():
        return few  # 1,5 миллиона

    number = int(amount)
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few

    return many


def isk_in_words(value) -> str:
    """
    An amount in words for reports: 275 миллионов, 1,5 миллиона.

    Amounts below a million have no words (an empty text): the number is shown
    next to it anyway, so words would only repeat it.
    """

    if value is None:
        return ""

    amount = Decimal(str(value))

    for limit, forms in _SCALES:
        if amount >= limit:
            scaled = (amount / limit).quantize(Decimal("0.1"), rounding=ROUND_DOWN)

            return f"{_number_text(scaled)} {_plural(scaled, *forms)}"

    return ""


def _trim(value: str, limit: int) -> str:
    """Cut a text to a Discord limit"""

    if len(value) <= limit:
        return value

    return value[: limit - 3] + "..."


def build_payload(
    description: list[str] | None = None,
    fields: list[tuple[str, str]] | None = None,
) -> dict:
    """
    The body of a webhook request: one embed with the usual title and colour,
    and an @everyone mention.

    :param description: Lines of text under the title
    :param fields: (name, value) pairs; pairs with an empty value are left out
    """

    embed: dict = {"title": _trim(EMBED_TITLE, TITLE_LIMIT), "color": EMBED_COLOR}

    text = "\n".join(line.rstrip() for line in (description or []) if line.strip())
    if text:
        embed["description"] = _trim(text, DESCRIPTION_LIMIT)

    shown = [
        {
            "name": _trim(str(name), FIELD_NAME_LIMIT),
            "value": _trim(str(value).strip(), FIELD_VALUE_LIMIT),
            "inline": False,
        }
        for name, value in (fields or [])
        if name and str(value).strip()
    ][:MAX_FIELDS]
    if shown:
        embed["fields"] = shown

    return {
        "content": EVERYONE_MENTION,
        "allowed_mentions": {"parse": ["everyone"]},
        "embeds": [embed],
    }


def _webhook(channel: str) -> tuple[str, str]:
    """
    The webhook URL and the thread ID of a channel (empty if not set).

    What an administrator saved in the Django admin wins. A channel that is empty
    there uses the setting from local.py, together with that setting's thread ID.
    """

    config = DiscordConfig.objects.first()

    if channel == CHANNEL_NEW_ORDER:
        if config is not None and config.new_order_webhook_url:
            return config.new_order_webhook_url, config.new_order_thread_id

        return (
            app_settings.EVEBUILDERS_DISCORD_NEW_ORDER_WEBHOOK_URL,
            app_settings.EVEBUILDERS_DISCORD_NEW_ORDER_THREAD_ID,
        )

    if channel == CHANNEL_COMPLETE:
        if config is not None and config.complete_webhook_url:
            return config.complete_webhook_url, config.complete_thread_id

        return (
            app_settings.EVEBUILDERS_DISCORD_COMPLETE_WEBHOOK_URL,
            app_settings.EVEBUILDERS_DISCORD_COMPLETE_THREAD_ID,
        )

    raise ValueError(f"Unknown notification channel: {channel}")


def notify_taken_enabled() -> bool:
    """
    Whether to announce that a builder took a part of an order: the choice made
    in the Django admin, or the setting from local.py when nothing was chosen.
    """

    config = DiscordConfig.objects.first()
    if config is not None and config.notify_taken is not None:
        return config.notify_taken

    return app_settings.EVEBUILDERS_DISCORD_NOTIFY_TAKEN


def _retry_after(response) -> float | None:
    """How long Discord asks us to wait after a 429, in seconds"""

    value = response.headers.get("Retry-After")
    if value is None:
        try:
            value = response.json().get("retry_after")
        except (ValueError, AttributeError):
            return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def retry_delay(attempt: int, retry_after: float | None = None) -> int:
    """Seconds to wait before the next attempt: Discord's wish, or 30s, 60s, ..."""

    if retry_after is not None:
        return max(1, ceil(retry_after) + 1)

    return min(30 * 2**attempt, 900)


def deliver(channel: str, payload: dict) -> str:
    """
    Post a message to the webhook of a channel.

    :raises DiscordRetry: When trying again later may help (rate limit, Discord
        or network trouble)
    :return: "skipped" (no webhook set), "sent" or "rejected" (Discord refused
        the message for good, e.g. a wrong URL; logged)
    """

    url, thread_id = _webhook(channel)
    if not url:
        return "skipped"

    try:
        response = requests.post(
            url,
            json=payload,
            params={"thread_id": thread_id} if thread_id else None,
            headers={"User-Agent": f"aa-eve-builders/{__version__}"},
            timeout=DISCORD_TIMEOUT,
        )
    except requests.RequestException as ex:
        raise DiscordRetry(f"The Discord request failed: {ex}") from ex

    if response.status_code == 429:
        raise DiscordRetry("Discord rate limit", retry_after=_retry_after(response))

    if response.status_code >= 500:
        raise DiscordRetry(f"Discord answered HTTP {response.status_code}")

    if response.status_code >= 400:
        logger.error(
            "Discord refused a notification (channel %s, HTTP %s): %s",
            channel,
            response.status_code,
            response.text[:300],
        )

        return "rejected"

    return "sent"


def notify(channel: str, payload: dict) -> None:
    """
    Queue a notification. It is sent only after the current database
    transaction has been committed, so a rolled-back operation sends nothing.
    Nothing is queued when the channel has no webhook.
    """

    url, _thread_id = _webhook(channel)
    if not url:
        return

    def queue() -> None:
        # Imported here: the tasks module imports this one
        # AA EVE Builders
        from evebuilders.tasks import send_discord_notification

        send_discord_notification.delay(channel, payload)

    transaction.on_commit(queue)


def _count_form(count: int, one: str, few: str, many: str) -> str:
    """The Russian word form for a whole number: 1 / 2-4 / 5+ (21 is like 1)"""

    if count % 10 == 1 and count % 100 != 11:
        return one
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return few

    return many


def positions_for(count: int) -> str:
    """After the preposition "на": 1 позицию, 2 позиции, 5 позиций"""

    return f"{count} {_count_form(count, 'позицию', 'позиции', 'позиций')}"


def positions_of(count: int) -> str:
    """After the preposition "от": 1 позиции, 2 позиций, 5 позиций"""

    return f"{count} {_count_form(count, 'позиции', 'позиций', 'позиций')}"


# The emoji at the start of a message: what kind of event it is, at a glance
EMOJI_NEW = "\U0001f195"  # new order
EMOJI_CHANGED = "\u270f\ufe0f"  # order changed
EMOJI_DELETED = "\U0001f5d1\ufe0f"  # order deleted
EMOJI_TAKEN = "\U0001f4e6"  # a builder took a part
EMOJI_GIVEN_BACK = "\u21a9\ufe0f"  # a part was given back or released
EMOJI_WAITING = "\u23f3"  # a contract waits for acceptance
EMOJI_CREDITED = "\u2705"  # a contract was accepted and credited
EMOJI_CREDITED_BY_HAND = "\u2611\ufe0f"  # credited by a manager
EMOJI_INVALID = "\u274c"  # a contract cannot be counted
EMOJI_WARNING = "\u26a0\ufe0f"  # the ESI token stopped working


def add_emoji(payload: dict, emoji: str) -> dict:
    """
    Put an emoji before the first line of the message (before the title when
    the message has no text).

    :param payload: The body made by build_payload
    :return: The same payload
    """

    embed = payload["embeds"][0]
    if "description" in embed:
        embed["description"] = f"{emoji} {embed['description']}"
    else:
        embed["title"] = f"{emoji} {embed['title']}"

    return payload


def with_emoji(emoji: str):
    """A decorator for the functions that make a message: the message gets the emoji"""

    def decorator(function):
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            return add_emoji(function(*args, **kwargs), emoji)

        return wrapper

    return decorator
