"""The settings of the Discord notifications: the channels and where each kind goes"""

# Standard Library
from urllib.parse import urlparse

# Django
from django import forms
from django.utils.translation import gettext_lazy as _

# AA EVE Builders
from evebuilders import app_settings
from evebuilders.models import DiscordConfig
from evebuilders.notifications import (
    CHANNEL_COMPLETE,
    CHANNEL_NEW_ORDER,
    CHANNEL_REVIEW,
    EMOJI_CHANGED,
    EMOJI_CREDITED,
    EMOJI_CREDITED_BY_HAND,
    EMOJI_DELETED,
    EMOJI_GIVEN_BACK,
    EMOJI_INVALID,
    EMOJI_NEW,
    EMOJI_TAKEN,
    EMOJI_WAITING,
    EMOJI_WARNING,
    KIND_CONTRACT_CREDITED,
    KIND_CONTRACT_INVALID,
    KIND_CONTRACT_WAITING,
    KIND_GIVEN_BACK,
    KIND_MANUAL_CREDIT,
    KIND_NEW_ORDER,
    KIND_ORDER_CANCELLED,
    KIND_ORDER_CHANGED,
    KIND_RELEASED,
    KIND_TAKEN,
    KIND_TOKEN_FAILURE,
    OFF,
    DiscordRetry,
    _webhook,
    build_payload,
    deliver,
    route_of,
)

# The channels in the order they are shown
CHANNEL_ORDER = (CHANNEL_NEW_ORDER, CHANNEL_REVIEW, CHANNEL_COMPLETE)

# The names of the channels as people see them
CHANNEL_NAMES = {
    CHANNEL_NEW_ORDER: _("New orders"),
    CHANNEL_REVIEW: _("On review"),
    CHANNEL_COMPLETE: _("Everything else"),
}

# The same names for the test message, which is written in Russian like the others
RUSSIAN_NAMES = {
    CHANNEL_NEW_ORDER: "Новые заказы",
    CHANNEL_REVIEW: "На проверке",
    CHANNEL_COMPLETE: "Всё остальное",
}

# The fields of DiscordConfig of a channel: the webhook and the thread
CHANNEL_FIELDS = {
    CHANNEL_NEW_ORDER: ("new_order_webhook_url", "new_order_thread_id"),
    CHANNEL_REVIEW: ("review_webhook_url", "review_thread_id"),
    CHANNEL_COMPLETE: ("complete_webhook_url", "complete_thread_id"),
}

# The setting of local.py that a channel falls back to (the third has none)
LOCAL_SETTINGS = {
    CHANNEL_NEW_ORDER: "EVEBUILDERS_DISCORD_NEW_ORDER_WEBHOOK_URL",
    CHANNEL_COMPLETE: "EVEBUILDERS_DISCORD_COMPLETE_WEBHOOK_URL",
}

# The kinds of messages in the order they are shown: the emoji and the name
KIND_INFO = {
    KIND_NEW_ORDER: (EMOJI_NEW, _("New order")),
    KIND_ORDER_CHANGED: (EMOJI_CHANGED, _("Order changed")),
    KIND_ORDER_CANCELLED: (EMOJI_DELETED, _("Order deleted")),
    KIND_TAKEN: (EMOJI_TAKEN, _("A builder took a part")),
    KIND_GIVEN_BACK: (EMOJI_GIVEN_BACK, _("A builder gave a part back")),
    KIND_RELEASED: (EMOJI_GIVEN_BACK, _("A manager released a part")),
    KIND_CONTRACT_WAITING: (EMOJI_WAITING, _("A contract waits for acceptance")),
    KIND_CONTRACT_CREDITED: (
        EMOJI_CREDITED,
        _("A contract was accepted and credited"),
    ),
    KIND_MANUAL_CREDIT: (EMOJI_CREDITED_BY_HAND, _("Credited by hand")),
    KIND_CONTRACT_INVALID: (EMOJI_INVALID, _("A contract cannot be counted")),
    KIND_TOKEN_FAILURE: (EMOJI_WARNING, _("The ESI token stopped working")),
}

ROUTE_CHOICES = [(channel, CHANNEL_NAMES[channel]) for channel in CHANNEL_ORDER] + [
    (OFF, _("Off"))
]

# Only the addresses of Discord itself are taken: a manager must not be able to make
# the server send requests to any other address
_DISCORD_HOSTS = ("discord.com", "discordapp.com")


def is_discord_webhook(url: str) -> bool:
    """Whether an address is the webhook of a Discord channel"""

    parsed = urlparse(url)
    host = parsed.hostname or ""

    return (
        parsed.scheme == "https"
        and any(host == name or host.endswith(f".{name}") for name in _DISCORD_HOSTS)
        and parsed.path.startswith("/api/webhooks/")
    )


def _tail(url: str) -> str:
    """The end of an address, to recognise it without showing it"""

    return f"…{url[-6:]}" if url else ""


def channel_status(channel: str) -> dict:
    """
    Whether a channel has a webhook, and where it comes from. The address itself is
    never given.
    """

    config = DiscordConfig.objects.first()
    url = getattr(config, CHANNEL_FIELDS[channel][0], "") if config else ""
    if url:
        return {"source": "plugin", "tail": _tail(url)}

    local = getattr(app_settings, LOCAL_SETTINGS.get(channel, ""), "")
    if local:
        return {"source": "local", "tail": _tail(local)}

    return {"source": "none", "tail": ""}


def unreachable_kinds() -> list[str]:
    """The kinds of messages that go to a channel that has no webhook"""

    names = []
    for kind, (emoji, label) in KIND_INFO.items():
        channel, _everyone = route_of(kind)
        if channel and not _webhook(channel)[0]:
            names.append(f"{emoji} {label}")

    return names


def reset_routes() -> None:
    """Every kind of message goes where it went by default"""

    config = DiscordConfig.objects.first()
    if config is not None:
        config.routes = {}
        config.save(update_fields=["routes", "updated_at"])


def send_test_message(channel: str) -> str:
    """
    Send a test message to a channel, without the mention of everyone.

    :return: sent, skipped (no webhook), rejected or busy (try again later)
    """

    payload = build_payload(
        [
            f"Это тестовое сообщение: канал «{RUSSIAN_NAMES[channel]}» настроен.",
            "Его можно удалить.",
        ],
        mention=False,
    )
    try:
        return deliver(channel, payload)
    except DiscordRetry:
        return "busy"


class DiscordSettingsForm(forms.Form):
    """
    The webhooks of the channels and the route of every kind of message. The
    fields are made for the channels and the kinds, and rows of bound fields are
    kept for the template.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        config = DiscordConfig.objects.first()

        self.channel_rows = []
        for channel in CHANNEL_ORDER:
            thread = getattr(config, CHANNEL_FIELDS[channel][1], "") if config else ""
            self.fields[f"url_{channel}"] = forms.CharField(
                required=False,
                max_length=500,
                widget=forms.TextInput(
                    attrs={
                        "class": "form-control form-control-sm",
                        "autocomplete": "off",
                        "placeholder": "https://discord.com/api/webhooks/...",
                    }
                ),
            )
            self.fields[f"thread_{channel}"] = forms.CharField(
                required=False,
                max_length=32,
                initial=thread,
                widget=forms.TextInput(
                    attrs={"class": "form-control form-control-sm", "size": 20}
                ),
            )
            self.fields[f"clear_{channel}"] = forms.BooleanField(required=False)
            self.channel_rows.append(
                {
                    "channel": channel,
                    "name": CHANNEL_NAMES[channel],
                    "status": channel_status(channel),
                    "url": self[f"url_{channel}"],
                    "thread": self[f"thread_{channel}"],
                    "clear": self[f"clear_{channel}"],
                }
            )

        self.kind_rows = []
        for kind, (emoji, label) in KIND_INFO.items():
            channel, everyone = route_of(kind)
            self.fields[f"route_{kind}"] = forms.ChoiceField(
                required=False,
                choices=ROUTE_CHOICES,
                initial=channel,
                widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
            )
            self.fields[f"everyone_{kind}"] = forms.BooleanField(
                required=False, initial=everyone
            )
            self.kind_rows.append(
                {
                    "kind": kind,
                    "emoji": emoji,
                    "label": label,
                    "route": self[f"route_{kind}"],
                    "everyone": self[f"everyone_{kind}"],
                }
            )

    def clean(self):
        cleaned = super().clean()

        for channel in CHANNEL_ORDER:
            url = (cleaned.get(f"url_{channel}") or "").strip()
            if url and not is_discord_webhook(url):
                self.add_error(
                    f"url_{channel}",
                    _(
                        "The address must be a Discord webhook "
                        "(https://discord.com/api/webhooks/...)."
                    ),
                )

            thread = (cleaned.get(f"thread_{channel}") or "").strip()
            if thread and not thread.isdigit():
                self.add_error(f"thread_{channel}", _("The thread ID is a number."))

        return cleaned

    def save(self) -> DiscordConfig:
        """
        Save what the form says. An empty address keeps the saved one; the
        address is changed only by a new one and removed only on request.
        """

        config = DiscordConfig.objects.first() or DiscordConfig()
        data = self.cleaned_data

        for channel in CHANNEL_ORDER:
            url_field, thread_field = CHANNEL_FIELDS[channel]
            if data[f"clear_{channel}"]:
                setattr(config, url_field, "")
                setattr(config, thread_field, "")
                continue

            url = data[f"url_{channel}"].strip()
            if url:
                setattr(config, url_field, url)
            setattr(config, thread_field, data[f"thread_{channel}"].strip())

        config.routes = {
            kind: {
                "channel": data[f"route_{kind}"],
                "everyone": data[f"everyone_{kind}"],
            }
            for kind in KIND_INFO
        }
        config.save()

        return config
