"""App Views"""

# Django
from django.contrib import messages
from django.contrib.auth.decorators import (
    login_required,
    permission_required,
    user_passes_test,
)
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

# AA EVE Builders
from evebuilders import app_settings
from evebuilders.catalog import (
    SyncResult,
    catalog_overview,
    search_items,
    start_catalog_sync,
)
from evebuilders.models import CatalogSync
from evebuilders.permissions import MANAGE_ACCESS, has_any_access


@login_required
@user_passes_test(has_any_access)
def index(request: WSGIRequest) -> HttpResponse:
    """
    Index view
    :param request:
    :return:
    """

    context = {"text": "Hello, World!"}

    return render(request, "evebuilders/index.html", context)


@login_required
@permission_required(MANAGE_ACCESS)
def settings_view(request: WSGIRequest) -> HttpResponse:
    """
    Plugin settings (managers only): item catalog state and the update button
    :param request:
    :return:
    """

    context = {
        "sync": CatalogSync.get_solo(),
        "rows": catalog_overview(),
        "min_interval": app_settings.EVEBUILDERS_CATALOG_MIN_INTERVAL_MINUTES,
    }

    return render(request, "evebuilders/settings.html", context)


@login_required
@permission_required(MANAGE_ACCESS)
@require_POST
def start_sync(request: WSGIRequest) -> HttpResponse:
    """
    Start an item catalog sync (managers only) and go back to the settings page
    :param request:
    :return:
    """

    result = start_catalog_sync(user=request.user)

    if result is SyncResult.STARTED:
        messages.success(
            request,
            _(
                "Catalog sync started. Loading runs in the background and "
                "can take several minutes."
            ),
        )
    elif result is SyncResult.TOO_SOON:
        messages.warning(
            request,
            _("A sync was started less than %(minutes)s minutes ago, please wait.")
            % {"minutes": app_settings.EVEBUILDERS_CATALOG_MIN_INTERVAL_MINUTES},
        )
    elif result is SyncResult.ESI_OFFLINE:
        messages.error(request, _("ESI appears to be offline, try again later."))
    elif result is SyncResult.NOTHING_TO_LOAD:
        messages.warning(
            request, _("No categories or groups are configured, nothing to load.")
        )
    else:
        messages.error(
            request,
            _("Could not start the sync: %(error)s")
            % {"error": CatalogSync.get_solo().last_error},
        )

    return redirect("evebuilders:settings")

@login_required
@permission_required(MANAGE_ACCESS)
@require_GET
def item_search(request: WSGIRequest) -> JsonResponse:
    """
    Search the item catalog by name (managers only), for the order form
    :param request: GET parameter ``q`` holds part of the item name
    :return: JSON: {"results": [{"id", "name", "group", "category"}, ...]}
    """

    return JsonResponse({"results": search_items(request.GET.get("q", ""))})