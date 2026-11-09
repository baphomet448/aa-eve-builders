"""Send a test message to the configured Discord webhooks"""

# Django
from django.core.management.base import BaseCommand

# AA EVE Builders
from evebuilders.notifications import (
    CHANNEL_COMPLETE,
    CHANNEL_NEW_ORDER,
    DiscordRetry,
    build_payload,
    deliver,
)

CHANNELS = (
    (CHANNEL_NEW_ORDER, "new orders (industry-new-order-ping)"),
    (CHANNEL_COMPLETE, "reports (industry-complete-ping)"),
)

RESULTS = {
    "sent": "sent",
    "skipped": "no webhook is configured, nothing was sent",
    "rejected": "Discord refused the message, check the webhook URL (see the log)",
}


class Command(BaseCommand):
    """Management command: evebuilders_test_notification"""

    help = (
        "Sends one test message to every configured Discord webhook, so the "
        "settings can be checked. The message mentions @everyone."
    )

    def handle(self, *args, **options):
        for channel, label in CHANNELS:
            payload = build_payload(
                [
                    "Это тестовое сообщение плагина PROB Builders. "
                    "Если вы его видите, вебхук настроен правильно."
                ],
                [("Канал", label)],
            )

            try:
                result = RESULTS[deliver(channel, payload)]
            except DiscordRetry as ex:
                result = f"Discord did not take it now, try again later ({ex})"

            self.stdout.write(f"{label}: {result}")
