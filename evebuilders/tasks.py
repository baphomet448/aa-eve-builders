"""App Tasks"""

# Standard Library
import logging

# Third Party
from celery import shared_task

# Django
from django.utils import timezone

# AA EVE Builders
from evebuilders.catalog import start_catalog_sync
from evebuilders.models import ContractSource
from evebuilders.notifications import DiscordRetry, deliver, retry_delay
from evebuilders.sync import next_sync_time, sync_now

logger = logging.getLogger(__name__)


@shared_task
def sync_catalog() -> str:
    """
    Scheduled item catalog sync.

    The schedule itself is added by the AA admin in local.py
    (CELERYBEAT_SCHEDULE), see the README.
    """

    result = start_catalog_sync()
    logger.info("Scheduled catalog sync: %s", result.value)

    return result.value


@shared_task
def sync_contracts() -> str:
    """
    Scheduled contract sync: read the corporation contracts from ESI and apply
    them to the orders (waiting, credited, invalid, closed).

    The schedule (every minute) is added by the AA admin in local.py
    (CELERYBEAT_SCHEDULE), see the README. Most runs do nothing: a sync is
    done only when ESI has a fresh answer (its cache has expired), or some
    minutes after a failed sync. A run that comes right after another one (for
    example a press of the Sync button) is skipped as well.

    :return: no_source, not_yet, too_soon, error or ok
    """

    source = ContractSource.get_solo()
    if source is None:
        return "no_source"

    if next_sync_time(source) > timezone.now():
        return "not_yet"

    attempt = sync_now()

    if attempt.too_soon:
        return "too_soon"

    report = attempt.report
    if report.error:
        logger.warning("Scheduled contract sync failed: %s", report.error)

        return "error"

    logger.info(
        "Scheduled contract sync: %s contracts seen, %s newly waiting, "
        "%s credited (%s items), %s closed, %s invalid, %s skipped",
        report.seen,
        report.pending,
        report.credited,
        report.credited_items,
        report.closed,
        report.invalid,
        report.skipped,
    )

    return "ok"


@shared_task(bind=True, max_retries=6)
def send_discord_notification(self, channel: str, payload: dict) -> str:
    """
    Post a notification to a Discord webhook, trying again when Discord is
    busy or not reachable.

    :param channel: evebuilders.notifications.CHANNEL_NEW_ORDER or CHANNEL_COMPLETE
    :param payload: The webhook body from notifications.build_payload
    :return: skipped, sent or rejected
    """

    try:
        return deliver(channel, payload)
    except DiscordRetry as ex:
        logger.warning(
            "A Discord notification will be tried again (attempt %s): %s",
            self.request.retries + 1,
            ex,
        )

        raise self.retry(
            exc=ex, countdown=retry_delay(self.request.retries, ex.retry_after)
        )