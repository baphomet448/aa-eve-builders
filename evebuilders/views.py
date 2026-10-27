"""App Views"""

# Standard Library
from datetime import timedelta

# Django
from django.contrib import messages
from django.contrib.auth.decorators import (
    login_required,
    permission_required,
    user_passes_test,
)
from django.core.exceptions import ValidationError
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
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
from evebuilders.forms import OrderForm
from evebuilders.models import CatalogSync
from evebuilders.orders import create_order, visible_orders
from evebuilders.permissions import MANAGE_ACCESS, has_any_access

# The due date offered on a new order form
DEFAULT_DUE_DAYS = 7


@login_required
@user_passes_test(has_any_access)
def index(request: WSGIRequest) -> HttpResponse:
    """
    Entry point of the plugin: the order list
    :param request:
    :return:
    """

    return redirect("evebuilders:orders")


@login_required
@user_passes_test(has_any_access)
def order_list(request: WSGIRequest) -> HttpResponse:
    """
    The corporate orders the user may see (see visible_orders for the rules)
    :param request:
    :return:
    """

    return render(
        request,
        "evebuilders/order_list.html",
        {"orders": visible_orders(request.user)},
    )


@login_required
@permission_required(MANAGE_ACCESS)
def new_order(request: WSGIRequest) -> HttpResponse:
    """
    Create a corporate order (managers only)
    :param request:
    :return:
    """

    if request.method == "POST":
        form = OrderForm(request.POST)

        if form.is_valid():
            data = form.cleaned_data

            try:
                order = create_order(
                    user=request.user,
                    eve_type=data["eve_type"],
                    quantity=data["quantity"],
                    unit_price=data["unit_price"],
                    due_date=data["due_date"],
                    priority=data["priority"],
                    access_level=data["access_level"],
                    destination=data["destination"],
                    note=data["note"],
                )
            except ValidationError as ex:
                for message in ex.messages:
                    form.add_error(None, message)
            else:
                messages.success(
                    request, _("Order %(number)s created.") % {"number": order.number}
                )

                return redirect("evebuilders:orders")
    else:
        form = OrderForm(
            initial={
                "due_date": timezone.localdate() + timedelta(days=DEFAULT_DUE_DAYS)
            }
        )

    return render(request, "evebuilders/order_form.html", {"form": form})


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