"""Order helpers"""

# Standard Library
from datetime import date
from decimal import Decimal

# Django
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext as _

# EVE Universe
from eveuniverse.models import EveType

# AA EVE Builders
from evebuilders.models import (
    BuilderProfile,
    ContractSource,
    Order,
    OrderEvent,
    OrderSequence,
)
from evebuilders.permissions import MANAGE_ACCESS

# Orders a builder can still see: not finished and not cancelled
OPEN_STATUSES = (
    Order.Status.NEW,
    Order.Status.IN_PROGRESS,
    Order.Status.DISTRIBUTED,
)


def next_order_number(day: date | None = None) -> str:
    """
    Next order number, e.g. N20261018-1.

    The counter is kept per day in OrderSequence and read under a row lock, so
    two simultaneous requests never get the same number. Numbers are never
    reused, even after an order is deleted (the counter only goes up).

    :param day: The day the number is for, today (server time) by default
    :return: The order number
    """

    day = day or timezone.localdate()

    with transaction.atomic():
        sequence, _created = OrderSequence.objects.select_for_update().get_or_create(
            date=day
        )
        sequence.last_number += 1
        sequence.save(update_fields=["last_number"])

    return f"N{day:%Y%m%d}-{sequence.last_number}"


def _receiver_corporation(user) -> tuple[int, str]:
    """
    The corporation a corporate order is for.

    The corporation of the connected ESI source if there is one, otherwise
    the corporation of the creator's main character.
    """

    source = ContractSource.get_solo()
    if source is not None:
        return source.corporation_id, source.corporation_name

    main_character = user.profile.main_character
    if main_character is not None:
        return main_character.corporation_id, main_character.corporation_name

    raise ValidationError(
        _("The corporation is unknown. Please set a main character first.")
    )


def create_order(
    *,
    user,
    eve_type: EveType,
    quantity: int,
    unit_price: Decimal,
    due_date: date,
    priority: str = Order.Priority.MEDIUM,
    access_level: int = Order.AccessLevel.BASE,
    destination: str = "",
    note: str = "",
) -> Order:
    """
    Create a corporate order for the corporation.

    Permissions are checked by the caller (the view), not here.

    :param user: The manager who creates the order
    :raises django.core.exceptions.ValidationError: When the data is not valid.
        Nothing is created and no order number is used up in that case.
    :return: The new order
    """

    corporation_id, corporation_name = _receiver_corporation(user)

    order = Order(
        kind=Order.Kind.CORPORATE,
        eve_type=eve_type,
        quantity=quantity,
        unit_price=unit_price,
        priority=priority,
        due_date=due_date,
        destination=destination,
        receiver_type=Order.ReceiverType.CORPORATION,
        receiver_id=corporation_id,
        receiver_name=corporation_name,
        note=note,
        access_level=access_level,
        created_by=user,
        updated_by=user,
    )

    # Validate before taking a number, so a failed attempt does not use one up
    order.full_clean(exclude=["number"])

    if due_date < timezone.localdate():
        raise ValidationError({"due_date": _("The due date cannot be in the past.")})

    with transaction.atomic():
        order.number = next_order_number()
        order.save()
        OrderEvent.objects.create(
            order=order,
            kind=OrderEvent.Kind.CREATED,
            actor=user,
            description=f"{quantity} x {eve_type.name}, {unit_price} ISK each",
        )

    return order


def builder_level(user) -> int:
    """The access level of a builder. Without a profile that is BASE."""

    profile = BuilderProfile.objects.filter(user=user).first()

    return profile.level if profile else Order.AccessLevel.BASE


def visible_orders(user):
    """
    The corporate orders the user may see, with the numbers for the list.

    Managers see every order. Builders see only open orders whose access level
    is not higher than their own; everything else is hidden from them entirely.

    Each order gets ``taken`` (sum of the builders' shares), ``credited``
    (what is already counted as done) and ``free`` (quantity minus taken).
    """

    orders = Order.objects.filter(kind=Order.Kind.CORPORATE)

    if not user.has_perm(MANAGE_ACCESS):
        orders = orders.filter(
            status__in=OPEN_STATUSES, access_level__lte=builder_level(user)
        )

    return (
        orders.select_related("eve_type")
        .annotate(
            taken=Coalesce(Sum("assignments__taken"), 0),
            credited=Coalesce(Sum("assignments__credited"), 0),
        )
        .annotate(free=F("quantity") - F("taken"))
        .order_by("due_date", "-created_at")
    )