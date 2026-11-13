"""App Views"""

# Standard Library
from datetime import timedelta

# Django
from django.contrib import messages
from django.contrib.auth.decorators import (
    login_required,
    user_passes_test,
)
from django.core.exceptions import ValidationError
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

# Alliance Auth
# Alliance Auth (External Libs)
from esi.decorators import token_required

# AA EVE Builders
from evebuilders import app_settings
from evebuilders.catalog import (
    SyncResult,
    catalog_overview,
    search_items,
    start_catalog_sync,
)
from evebuilders.contracts import CONTRACTS_SCOPE, EsiError, connect_source
from evebuilders.discord_settings import (
    CHANNEL_NAMES,
    DiscordSettingsForm,
    reset_routes,
    send_test_message,
    unreachable_kinds,
)
from evebuilders.forms import OrderEditForm, OrderForm
from evebuilders.history import EVENT_KINDS, history_result
from evebuilders.levels import (
    builder_users,
    level_rows,
    set_builder_level,
    set_manager_role,
)
from evebuilders.manager_actions import (
    can_delete_order,
    cancel_order,
    credit_manually,
    item_is_locked,
    release_share,
    update_order,
)
from evebuilders.messages import display_name
from evebuilders.models import CatalogSync, ContractSource, Destination, Order
from evebuilders.notifications import CHANNELS
from evebuilders.order_detail import contract_rows, event_rows, share_rows
from evebuilders.orders import (
    create_order,
    discard_share,
    my_shares,
    problem_contracts,
    recipient_name,
    take_order,
    visible_orders,
)
from evebuilders.overview import (
    problem_contract_rows,
    waiting_contract_rows,
)
from evebuilders.permissions import admin_required, has_any_access, manager_required
from evebuilders.places import (
    SEARCH_MIN_LENGTH,
    add_destination,
    search_systems,
    system_stations,
)
from evebuilders.statistics import collect_statistics
from evebuilders.sync import next_sync_time, sync_now

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
@manager_required
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
@admin_required
def settings_view(request: WSGIRequest) -> HttpResponse:
    """
    Plugin settings (managers only): item catalog state and the update button
    :param request:
    :return:
    """

    context = {
        "sync": CatalogSync.get_solo(),
        "source": ContractSource.get_solo(),
        "rows": catalog_overview(),
        "min_interval": app_settings.EVEBUILDERS_CATALOG_MIN_INTERVAL_MINUTES,
    }

    return render(request, "evebuilders/settings.html", context)


@login_required
@admin_required
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
@manager_required
@require_GET
def item_search(request: WSGIRequest) -> JsonResponse:
    """
    Search the item catalog by name (managers only), for the order form
    :param request: GET parameter ``q`` holds part of the item name
    :return: JSON: {"results": [{"id", "name", "group", "category"}, ...]}
    """

    return JsonResponse({"results": search_items(request.GET.get("q", ""))})


@login_required
@user_passes_test(has_any_access)
@require_POST
def take_order_view(request: WSGIRequest, order_id: int) -> HttpResponse:
    """
    A builder takes a part of an order
    :param request: POST parameter ``quantity``
    :param order_id: The order
    :return:
    """

    # Orders the user may not see do not exist for him
    order = get_object_or_404(visible_orders(request.user), pk=order_id)

    try:
        quantity = int(request.POST.get("quantity", ""))
    except ValueError:
        messages.error(request, _("Please enter how many items you take."))

        return redirect("evebuilders:orders")

    try:
        take_order(user=request.user, order_id=order.pk, quantity=quantity)
    except ValidationError as ex:
        for message in ex.messages:
            messages.error(request, message)
    else:
        messages.success(
            request,
            _(
                "You took %(quantity)s x %(item)s of order %(number)s. When they "
                "are ready, create an item exchange contract to the corporation "
                "and put %(number)s into its title."
            )
            % {
                "quantity": quantity,
                "item": order.eve_type.name,
                "number": order.number,
            },
        )

    return redirect("evebuilders:orders")


@login_required
@user_passes_test(has_any_access)
@require_POST
def discard_view(request: WSGIRequest, order_id: int) -> HttpResponse:
    """
    A builder gives back what can still be given back of his share
    :param request:
    :param order_id: The order
    :return:
    """

    order = get_object_or_404(Order, pk=order_id, kind=Order.Kind.CORPORATE)

    try:
        quantity = discard_share(user=request.user, order_id=order.pk)
    except ValidationError as ex:
        for message in ex.messages:
            messages.error(request, message)
    else:
        messages.success(
            request,
            _("You gave back %(quantity)s items of order %(number)s.")
            % {"quantity": quantity, "number": order.number},
        )

    return redirect("evebuilders:my_orders")


@login_required
@user_passes_test(has_any_access)
def my_orders(request: WSGIRequest) -> HttpResponse:
    """
    The orders the user has taken
    :param request:
    :return:
    """

    source = ContractSource.get_solo()
    rows = my_shares(request.user)
    for row in rows:
        row["recipient"] = recipient_name(row["order"], source)

    context = {
        "rows": rows,
        "problems": problem_contracts(request.user),
        "source": source,
        "next_check": next_sync_time(source) if source else None,
    }

    return render(request, "evebuilders/my_orders.html", context)


@login_required
@admin_required
@token_required(scopes=CONTRACTS_SCOPE, new=True)
def connect_esi(request: WSGIRequest, token) -> HttpResponse:
    """
    Connect the token that is used to read the corporation contracts.

    django-esi sends the manager through the EVE login first and then calls
    this view with the new token.
    :param request:
    :param token: The new django-esi token
    :return:
    """

    try:
        source = connect_source(user=request.user, token=token)
    except ValidationError as ex:
        for message in ex.messages:
            messages.error(request, message)
    else:
        messages.success(
            request,
            _(
                "The corporation contracts are now read with the token of "
                "%(name)s (%(corporation)s)."
            )
            % {"name": token.character_name, "corporation": source.corporation_name},
        )

    return redirect("evebuilders:settings")


def _report_messages(request: WSGIRequest, report) -> None:
    """Tell the user what a contract sync did and what the state is now"""

    changes = []
    level = messages.INFO

    if report.credited:
        changes.append(
            _("%(count)s contract(s) credited (%(items)s items).")
            % {"count": report.credited, "items": report.credited_items}
        )
        level = messages.SUCCESS
    if report.pending:
        changes.append(
            _("%(count)s new contract(s) wait for acceptance.")
            % {"count": report.pending}
        )
    if report.closed:
        changes.append(
            _("%(count)s contract(s) ended without being accepted.")
            % {"count": report.closed}
        )
    if report.invalid:
        changes.append(
            _("%(count)s contract(s) cannot be counted, see the list below.")
            % {"count": report.invalid}
        )
        if level == messages.INFO:
            level = messages.WARNING
    if not changes:
        changes.append(_("Nothing changed since the last check."))

    messages.add_message(request, level, " ".join(changes))

    messages.info(
        request,
        _(
            "Right now %(waiting)s contract(s) wait for acceptance (%(items)s items) "
            "and %(problems)s cannot be counted. The plugin checks again "
            "automatically when ESI refreshes its data."
        )
        % {
            "waiting": report.waiting_contracts,
            "items": report.waiting_items,
            "problems": report.problem_contracts,
        },
    )


@login_required
@user_passes_test(has_any_access)
@require_POST
def sync_contracts_view(request: WSGIRequest) -> HttpResponse:
    """
    Read the corporation contracts now (the "Sync contracts" button)
    :param request:
    :return:
    """

    attempt = sync_now()

    if attempt.too_soon:
        messages.warning(
            request,
            _(
                "The contracts were checked a moment ago. Please wait %(seconds)s seconds."
            )
            % {"seconds": attempt.wait_seconds},
        )
    elif attempt.report.error:
        messages.error(
            request,
            _("The contracts could not be read: %(error)s")
            % {"error": attempt.report.error},
        )
    else:
        _report_messages(request, attempt.report)

    return redirect("evebuilders:my_orders")


@login_required
@manager_required
def builder_levels_view(request: WSGIRequest) -> HttpResponse:
    """
    The builders and their access levels (managers only)
    :param request:
    :return:
    """

    context = {"rows": level_rows(), "levels": Order.AccessLevel.choices}

    return render(request, "evebuilders/builder_levels.html", context)


@login_required
@manager_required
@require_POST
def set_level_view(request: WSGIRequest, user_id: int) -> HttpResponse:
    """
    Change the access level of a builder (managers only)
    :param request: POST parameter ``level``
    :param user_id: The builder
    :return:
    """

    user = get_object_or_404(builder_users(), pk=user_id)

    try:
        level = int(request.POST.get("level", ""))
        changed = set_builder_level(actor=request.user, user=user, level=level)
    except ValueError:
        messages.error(request, _("Please pick a level."))
    except ValidationError as ex:
        for message in ex.messages:
            messages.error(request, message)
    else:
        text = {"name": display_name(user), "level": Order.AccessLevel(level).label}
        if changed:
            messages.success(
                request, _("The level of %(name)s is now %(level)s.") % text
            )
        else:
            messages.info(request, _("The level of %(name)s did not change.") % text)

    return redirect("evebuilders:builder_levels")


@login_required
@admin_required
@require_POST
def set_manager_view(request: WSGIRequest, user_id: int) -> HttpResponse:
    """
    Make a builder a manager, or take the role away (admins only)
    :param request: POST parameter ``manager``: 1 to make a manager, 0 to take away
    :param user_id: The builder
    :return:
    """

    user = get_object_or_404(builder_users(), pk=user_id)
    make = request.POST.get("manager") == "1"
    text = {"name": display_name(user)}

    try:
        changed = set_manager_role(actor=request.user, user=user, manager=make)
    except ValidationError as ex:
        for message in ex.messages:
            messages.error(request, message)
    else:
        if make and changed:
            messages.success(request, _("%(name)s is now a manager.") % text)
        elif make:
            messages.info(request, _("%(name)s is a manager already.") % text)
        elif changed:
            messages.success(request, _("%(name)s is no longer a manager.") % text)
        else:
            messages.info(request, _("%(name)s was not a manager.") % text)

    return redirect("evebuilders:builder_levels")


@login_required
@manager_required
def order_detail(request: WSGIRequest, order_id: int) -> HttpResponse:
    """
    Everything about one order: its builders, contracts and history (managers only)
    :param request:
    :param order_id: The order
    :return:
    """

    order = get_object_or_404(visible_orders(request.user), pk=order_id)

    context = {
        "order": order,
        "shares": share_rows(order),
        "contracts": contract_rows(order),
        "events": event_rows(order),
        "can_delete": can_delete_order(request.user, order),
    }

    return render(request, "evebuilders/order_detail.html", context)


@login_required
@manager_required
@require_POST
def release_view(request: WSGIRequest, order_id: int) -> HttpResponse:
    """
    A manager takes items back from a builder
    :param request: POST parameters ``share`` and, optionally, ``quantity``
    :param order_id: The order
    :return:
    """

    order = get_object_or_404(Order, pk=order_id, kind=Order.Kind.CORPORATE)

    try:
        assignment_id = int(request.POST.get("share", ""))
        raw_quantity = request.POST.get("quantity", "").strip()
        quantity = int(raw_quantity) if raw_quantity else None
        released = release_share(
            actor=request.user,
            order_id=order.pk,
            assignment_id=assignment_id,
            quantity=quantity,
        )
    except ValueError:
        messages.error(request, _("Please check the numbers."))
    except ValidationError as ex:
        for message in ex.messages:
            messages.error(request, message)
    else:
        messages.success(
            request,
            _("%(quantity)s items of order %(number)s are free again.")
            % {"quantity": released, "number": order.number},
        )

    return redirect("evebuilders:order_detail", order_id=order.pk)


@login_required
@manager_required
@require_POST
def credit_view(request: WSGIRequest, order_id: int) -> HttpResponse:
    """
    A manager credits items to a builder by hand
    :param request: POST parameters ``share``, ``quantity`` and, optionally,
        ``contract`` and ``comment``
    :param order_id: The order
    :return:
    """

    order = get_object_or_404(Order, pk=order_id, kind=Order.Kind.CORPORATE)

    try:
        assignment_id = int(request.POST.get("share", ""))
        quantity = int(request.POST.get("quantity", ""))
        raw_contract = request.POST.get("contract", "").strip()
        contract_id = int(raw_contract) if raw_contract else None
        credited = credit_manually(
            actor=request.user,
            order_id=order.pk,
            assignment_id=assignment_id,
            quantity=quantity,
            comment=request.POST.get("comment", "")[:200],
            contract_id=contract_id,
        )
    except ValueError:
        messages.error(request, _("Please check the numbers."))
    except ValidationError as ex:
        for message in ex.messages:
            messages.error(request, message)
    else:
        messages.success(
            request,
            _("%(quantity)s items of order %(number)s were credited.")
            % {"quantity": credited, "number": order.number},
        )

    return redirect("evebuilders:order_detail", order_id=order.pk)


@login_required
@manager_required
def edit_order(request: WSGIRequest, order_id: int) -> HttpResponse:
    """
    Change an order (managers only)
    :param request:
    :param order_id: The order
    :return:
    """

    order = get_object_or_404(
        Order.objects.select_related("eve_type"),
        pk=order_id,
        kind=Order.Kind.CORPORATE,
    )
    locked = item_is_locked(order)
    initial = {
        "item_text": order.eve_type.name,
        "eve_type_id": order.eve_type_id,
        "quantity": order.quantity,
        "unit_price": order.unit_price,
        "priority": order.priority,
        "due_date": order.due_date,
        "access_level": order.access_level,
        "destination": order.destination,
        "note": order.note,
    }

    if request.method == "POST":
        form = OrderEditForm(
            request.POST, initial=initial, order=order, item_locked=locked
        )

        if form.is_valid():
            data = form.cleaned_data
            values = {
                "eve_type": data["eve_type"],
                "quantity": data["quantity"],
                "unit_price": data["unit_price"],
                "priority": data["priority"],
                "due_date": data["due_date"],
                "access_level": data["access_level"],
                "destination": data["destination"],
                "note": data["note"],
            }

            try:
                changes = update_order(
                    actor=request.user, order_id=order.pk, values=values
                )
            except ValidationError as ex:
                for message in ex.messages:
                    form.add_error(None, message)
            else:
                if changes:
                    messages.success(
                        request,
                        _("Order %(number)s was changed.") % {"number": order.number},
                    )
                else:
                    messages.info(request, _("Nothing was changed."))

                return redirect("evebuilders:order_detail", order_id=order.pk)
    else:
        form = OrderEditForm(initial=initial, order=order, item_locked=locked)

    context = {"form": form, "order": order, "editing": True, "item_locked": locked}

    return render(request, "evebuilders/order_form.html", context)


@login_required
@manager_required
@require_POST
def delete_order(request: WSGIRequest, order_id: int) -> HttpResponse:
    """
    Delete (cancel) an order (managers only)
    :param request: POST parameter ``reason``, optional
    :param order_id: The order
    :return:
    """

    order = get_object_or_404(Order, pk=order_id, kind=Order.Kind.CORPORATE)

    try:
        cancel_order(
            actor=request.user,
            order_id=order.pk,
            reason=request.POST.get("reason", "")[:200],
        )
    except ValidationError as ex:
        for message in ex.messages:
            messages.error(request, message)

        return redirect("evebuilders:order_detail", order_id=order.pk)

    messages.success(
        request, _("Order %(number)s was deleted.") % {"number": order.number}
    )

    return redirect("evebuilders:orders")


@login_required
@manager_required
def management(request: WSGIRequest) -> HttpResponse:
    """
    The tab "Contracts" of the management: contracts that cannot be counted and
    contracts that wait for acceptance (managers only)
    :param request:
    :return:
    """

    context = {
        "problems": problem_contract_rows(),
        "waiting": waiting_contract_rows(),
    }

    return render(request, "evebuilders/management.html", context)


@login_required
@manager_required
def management_statistics(request: WSGIRequest) -> HttpResponse:
    """
    The tab "Statistics" of the management (managers only)
    :param request:
    :return:
    """

    context = {"stats": collect_statistics()}

    return render(request, "evebuilders/management_statistics.html", context)


@login_required
@manager_required
def management_history(request: WSGIRequest) -> HttpResponse:
    """
    The tab "History" of the management: the events of all orders with a filter, a
    sorting and pages (managers only)
    :param request:
    :return:
    """

    context = {"result": history_result(request.GET), "kinds": EVENT_KINDS}

    return render(request, "evebuilders/management_history.html", context)


@login_required
@manager_required
def stations_view(request: WSGIRequest) -> HttpResponse:
    """
    The places orders can be delivered to, and a search to add more (managers only)
    :param request: GET parameter ``q`` (a part of a system name) or ``system``
        (the ID of a system whose stations to show)
    :return:
    """

    query = request.GET.get("q", "").strip()
    system_id = request.GET.get("system", "")
    context = {
        "places": Destination.objects.all(),
        "query": query,
        "searched": False,
        "too_short": 0 < len(query) < SEARCH_MIN_LENGTH and not system_id.isdigit(),
        "systems": [],
        "system": None,
        "stations": [],
    }

    try:
        if system_id.isdigit():
            found = system_stations(int(system_id))
            context.update(system=found["system"], stations=found["stations"])
            context["searched"] = True
        elif query:
            systems = search_systems(query)
            context["searched"] = True
            if len(systems) == 1:
                found = system_stations(systems[0]["id"])
                context.update(system=found["system"], stations=found["stations"])
            else:
                context["systems"] = systems
    except EsiError as ex:
        messages.error(request, _("ESI could not be read: %(error)s") % {"error": ex})

    return render(request, "evebuilders/stations.html", context)


@login_required
@manager_required
@require_POST
def add_station_view(request: WSGIRequest) -> HttpResponse:
    """
    Add a place to the list (managers only)
    :param request: POST parameters ``system_id`` and, optionally, ``station_id``
        and ``structure_name``
    :return:
    """

    try:
        system_id = int(request.POST.get("system_id", ""))
        raw_station = request.POST.get("station_id", "").strip()
        station_id = int(raw_station) if raw_station else None
        place = add_destination(
            actor=request.user,
            system_id=system_id,
            station_id=station_id,
            structure_name=request.POST.get("structure_name", ""),
        )
    except ValueError:
        messages.error(request, _("Please check the numbers."))
    except ValidationError as ex:
        for message in ex.messages:
            messages.error(request, message)
    except EsiError as ex:
        messages.error(request, _("ESI could not be read: %(error)s") % {"error": ex})
    else:
        messages.success(request, _("%(place)s was added.") % {"place": place.label})

    return redirect("evebuilders:stations")


@login_required
@manager_required
@require_POST
def delete_station_view(request: WSGIRequest, place_id: int) -> HttpResponse:
    """
    Remove a place from the list (managers only). Orders that have it keep it.
    :param request:
    :param place_id: The place
    :return:
    """

    place = get_object_or_404(Destination, pk=place_id)
    label = place.label
    place.delete()

    messages.success(
        request,
        _("%(place)s was removed from the list. Orders that have it keep it.")
        % {"place": label},
    )

    return redirect("evebuilders:stations")


@login_required
@admin_required
def discord_settings(request: WSGIRequest) -> HttpResponse:
    """
    The tab "Discord" of the settings: the webhooks of the channels and where each
    kind of message goes (managers only)
    :param request:
    :return:
    """

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "reset_routes":
            reset_routes()
            messages.success(
                request, _("Every kind of message goes where it went by default.")
            )

            return redirect("evebuilders:discord_settings")

        form = DiscordSettingsForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _("The Discord settings were saved."))

            return redirect("evebuilders:discord_settings")
    else:
        form = DiscordSettingsForm()

    context = {"form": form, "unreachable": unreachable_kinds()}

    return render(request, "evebuilders/discord_settings.html", context)


@login_required
@admin_required
@require_POST
def discord_test(request: WSGIRequest) -> HttpResponse:
    """
    Send a test message (without the mention of everyone) to a channel
    :param request:
    :return:
    """

    channel = request.POST.get("channel", "")
    if channel not in CHANNELS:
        messages.error(request, _("Unknown channel."))

        return redirect("evebuilders:discord_settings")

    name = CHANNEL_NAMES[channel]
    result = send_test_message(channel)
    if result == "sent":
        messages.success(
            request,
            _('A test message was sent to the channel "%(channel)s".')
            % {"channel": name},
        )
    elif result == "skipped":
        messages.warning(
            request,
            _('The channel "%(channel)s" has no webhook.') % {"channel": name},
        )
    elif result == "rejected":
        messages.error(
            request,
            _(
                "Discord refused the message. Check the webhook address and the "
                "thread ID."
            ),
        )
    else:
        messages.warning(request, _("Discord does not answer now. Try again later."))

    return redirect("evebuilders:discord_settings")
