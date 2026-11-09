"""Order helpers"""

# Standard Library
from datetime import date
from decimal import Decimal

# Third Party
# EVE Universe
from eveuniverse.models import EveType

# Django
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import (
    Case,
    F,
    IntegerField,
    OuterRef,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext as _

# Alliance Auth
from allianceauth.authentication.models import CharacterOwnership

# AA EVE Builders
from evebuilders.messages import (
    discard_payload,
    display_name,
    new_order_payload,
    taken_payload,
)
from evebuilders.models import (
    BuilderProfile,
    ContractRecord,
    ContractSource,
    Order,
    OrderAssignment,
    OrderEvent,
    OrderSequence,
)
from evebuilders.notifications import (
    CHANNEL_COMPLETE,
    CHANNEL_NEW_ORDER,
    notify,
    notify_taken_enabled,
)
from evebuilders.permissions import MANAGE_ACCESS, has_any_access

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
        notify(CHANNEL_NEW_ORDER, new_order_payload(order))

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
        .annotate(
            free=F("quantity") - F("taken"),
            pending=Coalesce(
                Subquery(_waiting_quantity(), output_field=IntegerField()), Value(0)
            ),
        )
        .annotate(
            status_rank=_rank("status", STATUS_ORDER),
            priority_rank=_rank("priority", PRIORITY_ORDER),
        )
        .order_by("status_rank", "priority_rank", "-pk")
    )


def recalculate_status(order: Order) -> None:
    """
    Set the order status from its shares.

    Nothing taken is NEW, part taken is IN_PROGRESS, everything taken is
    DISTRIBUTED and everything credited is COMPLETED. A cancelled order stays
    cancelled.
    """

    if order.status == Order.Status.CANCELLED:
        return

    totals = order.assignments.aggregate(
        taken=Coalesce(Sum("taken"), 0), credited=Coalesce(Sum("credited"), 0)
    )

    if totals["credited"] >= order.quantity:
        status = Order.Status.COMPLETED
    elif totals["taken"] >= order.quantity:
        status = Order.Status.DISTRIBUTED
    elif totals["taken"] > 0:
        status = Order.Status.IN_PROGRESS
    else:
        status = Order.Status.NEW

    if status != order.status:
        order.status = status
        order.save(update_fields=["status", "updated_at"])


def take_order(*, user, order_id: int, quantity: int) -> OrderAssignment:
    """
    A builder takes a part of an order.

    The order row is locked while this runs, so two builders taking at the
    same moment can never take more than is free. Taking again raises the
    builder's single share of the order; it never touches contracts.

    :param user: The builder (or manager) who takes the part
    :param order_id: The order
    :param quantity: How many items to take
    :raises django.core.exceptions.ValidationError: When the order cannot be
        taken like this. Nothing is changed in that case.
    :return: The builder's share of the order
    """

    if not has_any_access(user):
        raise ValidationError(_("You are not allowed to take orders."))

    with transaction.atomic():
        order = Order.objects.select_for_update().get(
            pk=order_id, kind=Order.Kind.CORPORATE
        )

        # Orders the user may not see do not exist for him
        if not visible_orders(user).filter(pk=order.pk).exists():
            raise ValidationError(_("This order is not available to you."))

        if order.status not in OPEN_STATUSES:
            raise ValidationError(_("This order is closed."))

        taken = order.assignments.aggregate(total=Coalesce(Sum("taken"), 0))["total"]
        free = order.quantity - taken

        if quantity < 1:
            raise ValidationError(_("The quantity must be at least 1."))
        if quantity > free:
            raise ValidationError(
                _("Only %(free)s items are free in this order.") % {"free": free}
            )

        share, _created = OrderAssignment.objects.select_for_update().get_or_create(
            order=order, builder=user
        )
        share.taken += quantity
        share.save(update_fields=["taken", "updated_at"])

        OrderEvent.objects.create(
            order=order,
            assignment=share,
            kind=OrderEvent.Kind.TAKEN,
            actor=user,
            description=f"Took {quantity} (now {share.taken} in total)",
        )
        recalculate_status(order)

        if notify_taken_enabled():
            notify(
                CHANNEL_COMPLETE,
                taken_payload(
                    user=user, order=order, quantity=quantity, free=free - quantity
                ),
            )

    return share


def pending_quantity(share: OrderAssignment) -> int:
    """P: items of the share that sit in contracts waiting for acceptance."""

    return share.contracts.filter(state=ContractRecord.State.OUTSTANDING).aggregate(
        total=Coalesce(Sum("quantity"), 0)
    )["total"]


def releasable_quantity(share: OrderAssignment) -> int:
    """What the builder may still give back: taken - credited - pending (T - R - P)."""

    return max(share.taken - share.credited - pending_quantity(share), 0)


def discard_deadline(order: Order) -> date:
    """
    The last day a builder may give the order back: the middle of the time
    between the creation of the order and its due date.
    """

    created = timezone.localtime(order.created_at).date()

    return created + (order.due_date - created) / 2


def discard_share(*, user, order_id: int, quantity: int | None = None) -> int:
    """
    A builder gives back (part of) his share of an order.

    Only what is neither credited nor in a contract waiting for acceptance can
    be given back, and only until half of the time to the due date has passed.
    The order row is locked while this runs.

    :param user: The builder
    :param order_id: The order
    :param quantity: How many items to give back, everything possible by default
    :raises django.core.exceptions.ValidationError: When it cannot be done.
        Nothing is changed in that case.
    :return: How many items were given back
    """

    with transaction.atomic():
        order = Order.objects.select_for_update().get(
            pk=order_id, kind=Order.Kind.CORPORATE
        )
        share = (
            OrderAssignment.objects.select_for_update()
            .filter(order=order, builder=user)
            .first()
        )

        if share is None:
            raise ValidationError(_("You have not taken this order."))

        if order.status not in OPEN_STATUSES:
            raise ValidationError(_("This order is closed."))

        if timezone.localdate() > discard_deadline(order):
            raise ValidationError(
                _(
                    "It is too late to give this order back: more than half of "
                    "the time until the due date has passed. Please ask a manager."
                )
            )

        available = releasable_quantity(share)
        if available < 1:
            raise ValidationError(
                _(
                    "There is nothing to give back: everything is delivered or "
                    "waits for a contract to be accepted."
                )
            )

        if quantity is None:
            quantity = available
        if quantity < 1 or quantity > available:
            raise ValidationError(
                _("You can give back between 1 and %(available)s items.")
                % {"available": available}
            )

        share.taken -= quantity
        share.save(update_fields=["taken", "updated_at"])

        OrderEvent.objects.create(
            order=order,
            assignment=share,
            kind=OrderEvent.Kind.DISCARDED,
            actor=user,
            description=f"Gave back {quantity} (now {share.taken} in total)",
        )
        recalculate_status(order)

        taken = order.assignments.aggregate(total=Coalesce(Sum("taken"), 0))["total"]
        free = order.quantity - taken
        notify(
            CHANNEL_COMPLETE,
            discard_payload(user=user, order=order, quantity=quantity, free=free),
        )

    return quantity


def my_shares(user) -> list[dict]:
    """
    The user's own shares for the "My orders" page.

    Shares that were given back completely (nothing taken) are not listed.

    :return: One dict per share with the share, its order, the pending (P) and
        releasable (T - R - P) quantities, the last day for giving it back and
        whether giving back is possible right now
    """

    shares = (
        OrderAssignment.objects.filter(builder=user, taken__gt=0)
        .select_related("order__eve_type")
        .order_by("order__due_date", "-created_at")
    )
    today = timezone.localdate()

    rows = []
    for share in shares:
        releasable = releasable_quantity(share)
        deadline = discard_deadline(share.order)
        rows.append(
            {
                "share": share,
                "order": share.order,
                "pending": pending_quantity(share),
                "status": share_status(share),
                "status_rank": SHARE_STATUS_ORDER.index(share_status(share)),
                "priority_rank": PRIORITY_ORDER.index(share.order.priority),
                "total": share.order.unit_price * share.taken,
                "left": share.taken - share.credited,
                "left_total": share.order.unit_price * (share.taken - share.credited),
                "releasable": releasable,
                "discard_deadline": deadline,
                "can_discard": (
                    releasable > 0
                    and share.order.status in OPEN_STATUSES
                    and today <= deadline
                ),
            }
        )

    # The same idea as the order list: what still has to be delivered first, the
    # urgent ones first, newer orders first
    rows.sort(
        key=lambda row: (row["status_rank"], row["priority_rank"], -row["order"].pk)
    )

    return rows


def _waiting_quantity():
    """
    Subquery for visible_orders: the items of an order that sit in contracts
    waiting for acceptance. A subquery, so it cannot multiply the sums of the
    shares.
    """

    return (
        ContractRecord.objects.filter(
            order=OuterRef("pk"), state=ContractRecord.State.OUTSTANDING
        )
        .order_by()
        .values("order")
        .annotate(total=Sum("quantity"))
        .values("total")
    )


def share_status(share: OrderAssignment) -> str:
    """
    How a builder's share is doing, for the "My orders" page.

    UNDER_REVIEW while a contract waits for acceptance, DONE when everything
    taken is credited, otherwise IN_PROGRESS.
    """

    if share.order.status == Order.Status.CANCELLED:
        return "CANCELLED"

    if pending_quantity(share) > 0:
        return "UNDER_REVIEW"

    if share.taken > 0 and share.credited >= share.taken:
        return "DONE"

    return "IN_PROGRESS"


def problem_contracts(user):
    """
    The contracts of the user's characters that were found but cannot be
    counted. A contract that is deleted later drops out of this list.
    """

    character_ids = CharacterOwnership.objects.filter(user=user).values_list(
        "character__character_id", flat=True
    )

    return (
        ContractRecord.objects.filter(
            state=ContractRecord.State.INVALID, issuer_character_id__in=character_ids
        )
        .select_related("order__eve_type")
        .order_by("-issued_at", "-created_at")
    )


# The order of the list: new orders first, finished and cancelled ones last
STATUS_ORDER = (
    Order.Status.NEW,
    Order.Status.IN_PROGRESS,
    Order.Status.DISTRIBUTED,
    Order.Status.COMPLETED,
    Order.Status.CANCELLED,
)
# Within a status: urgent orders first
PRIORITY_ORDER = (Order.Priority.HIGH, Order.Priority.MEDIUM, Order.Priority.LOW)


def _rank(field: str, values) -> Case:
    """The position of a field's value in an ordered list of values, for sorting"""

    return Case(
        *[
            When(**{field: value}, then=Value(position))
            for position, value in enumerate(values)
        ],
        default=Value(len(values)),
        output_field=IntegerField(),
    )


# The order of the shares on the "My orders" page: what is still to be delivered
# first, finished and cancelled ones last
SHARE_STATUS_ORDER = ("IN_PROGRESS", "UNDER_REVIEW", "DONE", "CANCELLED")

def recipient_name(order: Order, source) -> str:
    """
    Who the items of an order are delivered to: the corporation of the ESI
    connection for a corporate order, the customer for a private one.

    :param source: The connected ContractSource, or None
    :return: The name, empty if it is not known
    """

    if order.kind == Order.Kind.PRIVATE:
        return display_name(order.created_by) if order.created_by else ""

    return source.corporation_name if source else ""