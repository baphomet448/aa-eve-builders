"""Item catalog sync: start loading EVE types through eveuniverse"""

# Standard Library
import logging
from datetime import timedelta
from enum import Enum

# Django
from django.db import transaction
from django.utils import timezone

# EVE Universe
from eveuniverse.core.esitools import is_esi_online
from eveuniverse.tasks import load_eve_types

# AA EVE Builders
from evebuilders import app_settings
from evebuilders.models import CatalogSync

logger = logging.getLogger(__name__)


class SyncResult(str, Enum):
    """Outcome of a catalog sync request"""

    STARTED = "started"
    TOO_SOON = "too_soon"
    ESI_OFFLINE = "esi_offline"
    NOTHING_TO_LOAD = "nothing_to_load"
    FAILED = "failed"


def start_catalog_sync(user=None) -> SyncResult:
    """
    Start loading the configured categories and groups into eveuniverse.

    eveuniverse drops duplicate tasks silently, so double clicks are guarded
    here: a request is refused while the previous one started less than
    EVEBUILDERS_CATALOG_MIN_INTERVAL_MINUTES ago.

    :param user: The user who asked for the sync, or None for scheduled runs
    :return: What happened
    """

    category_ids = list(app_settings.EVEBUILDERS_CATALOG_CATEGORY_IDS)
    group_ids = list(app_settings.EVEBUILDERS_CATALOG_GROUP_IDS)

    if not category_ids and not group_ids:
        return SyncResult.NOTHING_TO_LOAD

    CatalogSync.get_solo()  # make sure the single row exists

    if not is_esi_online():
        CatalogSync.objects.filter(pk=1).update(
            last_error="ESI is offline, catalog sync not started"
        )
        return SyncResult.ESI_OFFLINE

    min_interval = timedelta(
        minutes=app_settings.EVEBUILDERS_CATALOG_MIN_INTERVAL_MINUTES
    )
    now = timezone.now()

    # Claim the slot under a row lock so two simultaneous requests cannot both start
    with transaction.atomic():
        state = CatalogSync.objects.select_for_update().get(pk=1)

        if state.started_at and now - state.started_at < min_interval:
            return SyncResult.TOO_SOON

        previous_started_at = state.started_at
        state.started_at = now
        state.started_by = user
        state.category_ids = ",".join(str(i) for i in category_ids)
        state.group_ids = ",".join(str(i) for i in group_ids)
        state.last_error = ""
        state.save()

    try:
        load_eve_types.delay(
            category_ids=category_ids or None, group_ids=group_ids or None
        )
    except Exception as ex:  # pylint: disable=broad-exception-caught
        # Typically the Celery broker is unreachable. Give the slot back so the
        # request can be repeated, and keep the reason for the settings page.
        logger.exception("Could not start the catalog sync")
        CatalogSync.objects.filter(pk=1).update(
            started_at=previous_started_at, last_error=f"{type(ex).__name__}: {ex}"
        )
        return SyncResult.FAILED

    logger.info(
        "Catalog sync started (categories: %s, groups: %s)", category_ids, group_ids
    )
    return SyncResult.STARTED