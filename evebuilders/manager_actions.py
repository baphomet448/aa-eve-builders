"""What a manager can do with the shares and contracts of an order"""

# Standard Library
from typing import Any, NamedTuple
# Django
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils.translation import gettext as _

# AA EVE Builders
from evebuilders.messages import (
    FIELD_LABELS,
    display_name,
    manual_credit_payload,
    order_changed_payload,
    released_payload,
    show_value,
)
from evebuilders.models import ContractRecord, Order, OrderAssignment, OrderEvent
from evebuilders.notifications import CHANNEL_COMPLETE, CHANNEL_NEW_ORDER, notify
from evebuilders.orders import OPEN_STATUSES, recalculate_status, releasable_quantity
from evebuilders.permissions import MANAGE_ACCESS


def _lock_share(actor, order_id: int, assignment_id: int):
    """
    Lock an order and one of its shares (in this order, like everything else)
    for a change by a manager.

    :raises django.core.exceptions.ValidationError: When the actor is not a
        manager or the share is not a share of this order
    :raises Order.DoesNotExist: When there is no such corporate order
    """

    if not actor.has_perm(MANAGE_ACCESS):
        raise ValidationError(_("Only managers can do this."))

    order = Order.objects.select_for_update().get(
        pk=order_id, kind=Order.Kind.CORPORATE
    )
    share = (
        OrderAssignment.objects.select_for_update()
        .select_related("builder")
        .filter(pk=assignment_id, order=order)
        .first()
    )
    if share is None:
        raise ValidationError(_("This share does not belong to the order."))

    return order, share


def _sum(queryset, field: str) -> int:
    return queryset.aggregate(total=Coalesce(Sum(field), 0))["total"]


def release_share(
    *, actor, order_id: int, assignment_id: int, quantity: int | None = None
) -> int:
    """
    A manager takes items back from a builder: they are free again.

    Only what is neither credited nor in a contract waiting for acceptance can
    be released (T - R - P). There is no time limit, unlike the builder's own
    "give back".

    :param quantity: How many items to release, everything possible by default
    :raises django.core.exceptions.ValidationError: When it cannot be done.
        Nothing is changed in that case.
    :return: How many items were released
    """

    with transaction.atomic():
        order, share = _lock_share(actor, order_id, assignment_id)

        available = releasable_quantity(share)
        if available < 1:
            raise ValidationError(
                _(
                    "There is nothing to release: everything is delivered or "
                    "waits for a contract to be accepted."
                )
            )

        if quantity is None:
            quantity = available
        if not 1 <= quantity <= available:
            raise ValidationError(
                _("You can release between 1 and %(available)s items.")
                % {"available": available}
            )

        share.taken -= quantity
        share.save(update_fields=["taken", "updated_at"])

        OrderEvent.objects.create(
            order=order,
            assignment=share,
            kind=OrderEvent.Kind.RELEASED,
            actor=actor,
            description=(
                f"Released {quantity} from {display_name(share.builder)} "
                f"(now {share.taken} in total)"
            ),
        )
        recalculate_status(order)

        free = order.quantity - _sum(order.assignments, "taken")
        notify(
            CHANNEL_COMPLETE,
            released_payload(
                manager=actor,
                builder=share.builder,
                order=order,
                quantity=quantity,
                free=free,
            ),
        )

    return quantity


def credit_manually(
    *,
    actor,
    order_id: int,
    assignment_id: int,
    quantity: int,
    comment: str = "",
    contract_id: int | None = None,
) -> int:
    """
    A manager counts items as delivered without the plugin having seen a valid
    accepted contract.

    With a contract ID the contract is closed by this: its record becomes
    "credited" (and so disappears from the builder's list of problem contracts
    and is never counted again by the sync). Without one, the items are just
    credited. Items in other contracts that wait for acceptance stay reserved.

    :param quantity: How many items to credit
    :param comment: Why (shown in the history and in Discord)
    :param contract_id: The in-game contract this is for, if any
    :raises django.core.exceptions.ValidationError: When it cannot be done.
        Nothing is changed in that case.
    :return: How many items were credited
    """

    comment = (comment or "").strip()

    with transaction.atomic():
        order, share = _lock_share(actor, order_id, assignment_id)

        record = None
        if contract_id is not None:
            record = (
                ContractRecord.objects.select_for_update()
                .filter(contract_id=contract_id)
                .first()
            )
            if record is None:
                raise ValidationError(
                    _("The contract %(id)s is not known to the plugin.")
                    % {"id": contract_id}
                )
            if record.state == ContractRecord.State.CREDITED:
                raise ValidationError(_("This contract is already credited."))

        waiting = share.contracts.filter(state=ContractRecord.State.OUTSTANDING)
        if record is not None:
            waiting = waiting.exclude(pk=record.pk)
        available = share.taken - share.credited - _sum(waiting, "quantity")

        if available < 1:
            raise ValidationError(
                _(
                    "There is nothing left to credit: everything is already "
                    "credited or waits in other contracts."
                )
            )
        if not 1 <= quantity <= available:
            raise ValidationError(
                _("You can credit between 1 and %(available)s items.")
                % {"available": available}
            )

        share.credited += quantity
        share.save(update_fields=["credited", "updated_at"])

        if record is not None:
            record.order = order
            record.assignment = share
            record.quantity = quantity
            record.state = ContractRecord.State.CREDITED
            record.reason = ""
            record.save()

        text = f"Credited {quantity} x {order.eve_type.name} manually"
        if record is not None:
            text += f" (contract {record.contract_id})"
        if comment:
            text += f": {comment}"
        OrderEvent.objects.create(
            order=order,
            assignment=share,
            kind=OrderEvent.Kind.MANUAL_CREDIT,
            actor=actor,
            description=text,
        )
        recalculate_status(order)

        remaining = order.quantity - _sum(order.assignments, "credited")
        notify(
            CHANNEL_COMPLETE,
            manual_credit_payload(
                manager=actor,
                builder=share.builder,
                order=order,
                quantity=quantity,
                remaining=remaining,
                comment=comment,
            ),
        )

    return quantity

# The fields of an order that a manager may change
EDITABLE_FIELDS = tuple(FIELD_LABELS)


class Change(NamedTuple):
    """One changed field of an order"""

    field: str
    old: Any
    new: Any


def item_is_locked(order: Order) -> bool:
    """
    Whether the item of an order can no longer be changed: builders took or
    delivered it, or there are contracts for it.
    """

    return (
        order.assignments.filter(Q(taken__gt=0) | Q(credited__gt=0)).exists()
        or ContractRecord.objects.filter(order=order).exists()
    )


def update_order(*, actor, order_id: int, values: dict) -> list[Change]:
    """
    A manager changes fields of an order.

    Only fields that really differ are changed; when nothing differs nothing
    is written and nothing is announced. The quantity cannot go below what is
    taken, the item cannot change once builders took the order, and the price
    cannot change while contracts wait for acceptance.

    :param values: New values by field name (see EDITABLE_FIELDS); fields that
        are missing are left alone
    :raises django.core.exceptions.ValidationError: When the change is not
        allowed or the values are not valid. Nothing is changed in that case.
    :return: The changes that were made, empty if there were none
    """

    if not actor.has_perm(MANAGE_ACCESS):
        raise ValidationError(_("Only managers can do this."))

    with transaction.atomic():
        order = (
            Order.objects.select_for_update()
            .select_related("eve_type")
            .get(pk=order_id, kind=Order.Kind.CORPORATE)
        )

        if order.status not in OPEN_STATUSES:
            raise ValidationError(_("A finished or cancelled order cannot be changed."))

        changes = [
            Change(field, getattr(order, field), values[field])
            for field in EDITABLE_FIELDS
            if field in values and values[field] != getattr(order, field)
        ]
        if not changes:
            return []

        changed = {change.field: change for change in changes}

        if "eve_type" in changed and item_is_locked(order):
            raise ValidationError(
                _(
                    "The item cannot be changed: builders already took or "
                    "delivered this order."
                )
            )

        if "quantity" in changed:
            taken = _sum(order.assignments, "taken")
            if changed["quantity"].new < taken:
                raise ValidationError(
                    _(
                        "The quantity cannot be lower than the %(taken)s items "
                        "that are already taken."
                    )
                    % {"taken": taken}
                )

        if (
            "unit_price" in changed
            and ContractRecord.objects.filter(
                order=order, state=ContractRecord.State.OUTSTANDING
            ).exists()
        ):
            raise ValidationError(
                _(
                    "The price cannot be changed while contracts for this order "
                    "wait for acceptance."
                )
            )

        for change in changes:
            setattr(order, change.field, change.new)
        order.updated_by = actor
        order.full_clean(exclude=["number"])
        order.save()

        description = "Order changed: " + "; ".join(
            f"{FIELD_LABELS[change.field][0]}: "
            f"{show_value(change.field, change.old, '(empty)')} -> "
            f"{show_value(change.field, change.new, '(empty)')}"
            for change in changes
        )
        OrderEvent.objects.create(
            order=order,
            kind=OrderEvent.Kind.UPDATED,
            actor=actor,
            description=description,
        )
        recalculate_status(order)

        notify(
            CHANNEL_NEW_ORDER,
            order_changed_payload(manager=actor, order=order, changes=changes),
        )

    return changes