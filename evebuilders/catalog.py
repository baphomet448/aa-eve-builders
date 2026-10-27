"""Item catalog sync: start loading EVE types through eveuniverse"""

# Standard Library
import logging
from datetime import timedelta
from enum import Enum

# Django
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Q, When
from django.utils import timezone

# EVE Universe
from eveuniverse.core.esitools import is_esi_online
from eveuniverse.models import EveCategory, EveGroup, EveType
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

def catalog_overview() -> list[dict]:
    """
    One row per configured category and group with the number of loaded types.

    Used by the settings page. A row is returned even when nothing is loaded
    yet (count 0), so the manager can see that a configured entry is empty.
    """

    category_ids = list(app_settings.EVEBUILDERS_CATALOG_CATEGORY_IDS)
    group_ids = list(app_settings.EVEBUILDERS_CATALOG_GROUP_IDS)

    category_names = dict(
        EveCategory.objects.filter(id__in=category_ids).values_list("id", "name")
    )
    category_counts = dict(
        EveType.objects.filter(eve_group__eve_category_id__in=category_ids)
        .order_by()
        .values_list("eve_group__eve_category_id")
        .annotate(total=Count("id"))
    )
    group_names = dict(
        EveGroup.objects.filter(id__in=group_ids).values_list("id", "name")
    )
    group_counts = dict(
        EveType.objects.filter(eve_group_id__in=group_ids)
        .order_by()
        .values_list("eve_group_id")
        .annotate(total=Count("id"))
    )

    rows = [
        {
            "kind": "category",
            "id": category_id,
            "name": category_names.get(category_id, ""),
            "count": category_counts.get(category_id, 0),
        }
        for category_id in category_ids
    ]
    rows += [
        {
            "kind": "group",
            "id": group_id,
            "name": group_names.get(group_id, ""),
            "count": group_counts.get(group_id, 0),
        }
        for group_id in group_ids
    ]

    return rows

ITEM_SEARCH_MIN_LENGTH = 2
ITEM_SEARCH_LIMIT = 20


def search_items(query: str, limit: int = ITEM_SEARCH_LIMIT) -> list[dict]:
    """
    Search the item catalog by name, for the order form.

    Only published types from the configured categories and groups are found.
    Names that start with the query come first, then names that contain it.

    :param query: Part of the item name (at least ITEM_SEARCH_MIN_LENGTH characters)
    :param limit: Maximum number of results
    :return: Dicts with id, name, group and category
    """

    query = query.strip()
    if len(query) < ITEM_SEARCH_MIN_LENGTH:
        return []

    eve_types = (
        catalog_types()
        .filter(name__icontains=query)
        .select_related("eve_group__eve_category")
        .annotate(
            rank=Case(
                When(name__istartswith=query, then=0),
                default=1,
                output_field=IntegerField(),
            )
        )
        .order_by("rank", "name")[:limit]
    )

    return [
        {
            "id": eve_type.id,
            "name": eve_type.name,
            "group": eve_type.eve_group.name,
            "category": eve_type.eve_group.eve_category.name,
        }
        for eve_type in eve_types
    ]

def catalog_types():
    """
    The types that can be ordered: published types from the configured
    categories and groups.

    :return: A queryset of EveType
    """

    in_catalog = Q(
        eve_group__eve_category_id__in=app_settings.EVEBUILDERS_CATALOG_CATEGORY_IDS
    ) | Q(eve_group_id__in=app_settings.EVEBUILDERS_CATALOG_GROUP_IDS)

    return EveType.objects.filter(in_catalog, published=True)