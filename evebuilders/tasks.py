"""App Tasks"""

# Standard Library
import logging

# Third Party
from celery import shared_task

# AA EVE Builders
from evebuilders.catalog import start_catalog_sync

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