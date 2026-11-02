"""
Deciding what a corporation contract means for the orders.

Nothing is changed here: classify_contract only returns a verdict. Applying the
verdicts (records, crediting) is done separately.
"""

# Standard Library
import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Callable

# Django
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.dateparse import parse_datetime

# Alliance Auth
from allianceauth.authentication.models import CharacterOwnership

# AA EVE Builders
from evebuilders import reasons
from evebuilders.models import ContractRecord, Order, OrderAssignment
from evebuilders.orders import OPEN_STATUSES, releasable_quantity
from evebuilders.reasons import reason_text

# An order number in the title of a contract, e.g. N20261027-2
ORDER_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])N\d{8}-\d+")

# Prices come from ESI as floats, so allow a tiny difference
PRICE_TOLERANCE = Decimal("0.01")


class Outcome(str, Enum):
    """What a contract means"""

    IGNORE = "ignore"  # not a delivery of ours, or nothing to do
    PENDING = "pending"  # valid, waits for acceptance ("under review")
    CREDIT = "credit"  # valid and accepted: count it
    CLOSED = "closed"  # a known contract that ended without success
    INVALID = "invalid"  # looks like a delivery but cannot be counted


@dataclass(frozen=True)
class Verdict:
    """The decision about one contract"""

    outcome: Outcome
    reason_code: str = ""  # one of evebuilders.reasons
    reason_data: dict = field(default_factory=dict)
    order: Order | None = None
    share: OrderAssignment | None = None
    quantity: int = 0
    price: Decimal = Decimal("0")

    @property
    def reason(self) -> str:
        """The reason in the current language, empty if there is none"""

        return reason_text(self.reason_code, self.reason_data)


def find_order_numbers(title: str) -> set[str]:
    """The order numbers that appear in a contract title"""

    return set(ORDER_NUMBER_RE.findall(title or ""))


def user_of_character(character_id):
    """The Auth user who owns the character, if there is one"""

    ownership = (
        CharacterOwnership.objects.filter(character__character_id=character_id)
        .select_related("user")
        .first()
    )

    return ownership.user if ownership else None


def _has_open_share(user) -> bool:
    """Whether the user still has something to deliver on an open order"""

    shares = OrderAssignment.objects.filter(
        builder=user, taken__gt=0, order__status__in=OPEN_STATUSES
    )

    return any(releasable_quantity(share) > 0 for share in shares)


def _is_expired(contract: dict, now) -> bool:
    """ESI keeps expired contracts as outstanding, so check the date"""

    expires = parse_datetime(contract.get("date_expired") or "")

    return expires is not None and expires < now


def classify_contract(
    contract: dict,
    *,
    corporation_id: int,
    items_loader: Callable[[int], list],
    now=None,
) -> Verdict:
    """
    Decide what a contract from the ESI list means for the orders.

    :param contract: One entry of the ESI list of corporation contracts
    :param corporation_id: The corporation the orders are for
    :param items_loader: Returns the ESI items of a contract. It is called only
        for contracts that passed all the cheaper checks.
    :param now: The current time (for tests)
    :return: The verdict
    """

    now = now or timezone.now()

    if (
        contract.get("type") != "item_exchange"
        or contract.get("assignee_id") != corporation_id
    ):
        return Verdict(Outcome.IGNORE)

    contract_id = contract["contract_id"]
    status = contract.get("status")
    existing = (
        ContractRecord.objects.filter(contract_id=contract_id)
        .select_related("order", "assignment")
        .first()
    )

    if existing is not None and existing.state == ContractRecord.State.CREDITED:
        return Verdict(Outcome.IGNORE)  # counted already

    closed = status not in ("outstanding", "finished") or (
        status == "outstanding" and _is_expired(contract, now)
    )
    if closed:
        if existing is None or existing.state not in (
            ContractRecord.State.OUTSTANDING,
            ContractRecord.State.INVALID,
        ):
            return Verdict(Outcome.IGNORE)

        return Verdict(
            Outcome.CLOSED,
            reason_code=reasons.CLOSED,
            reason_data={"status": str(status)},
            order=existing.order,
            share=existing.assignment,
            quantity=existing.quantity,
            price=existing.price,
        )

    issuer = user_of_character(contract.get("issuer_id"))
    numbers = find_order_numbers(contract.get("title") or "")

    if not numbers:
        # Foreign contracts are none of our business; but a builder who still
        # has something to deliver should hear that the number is missing
        if issuer is not None and _has_open_share(issuer):
            return Verdict(Outcome.INVALID, reason_code=reasons.NO_NUMBER)

        return Verdict(Outcome.IGNORE)

    if len(numbers) > 1:
        return Verdict(Outcome.INVALID, reason_code=reasons.MANY_NUMBERS)

    number = next(iter(numbers))
    order = Order.objects.filter(number=number, kind=Order.Kind.CORPORATE).first()
    if order is None:
        if issuer is None:
            return Verdict(Outcome.IGNORE)

        return Verdict(
            Outcome.INVALID,
            reason_code=reasons.UNKNOWN_ORDER,
            reason_data={"number": number},
        )

    if issuer is None:
        return Verdict(
            Outcome.INVALID, reason_code=reasons.NOT_ON_ACCOUNT, order=order
        )

    share = OrderAssignment.objects.filter(order=order, builder=issuer).first()
    if share is None or share.taken < 1:
        return Verdict(Outcome.INVALID, reason_code=reasons.NOT_TAKEN, order=order)

    if order.status == Order.Status.CANCELLED:
        return Verdict(
            Outcome.INVALID,
            reason_code=reasons.ORDER_CANCELLED,
            order=order,
            share=share,
        )

    items = items_loader(contract_id)
    quantity = sum(
        item.get("quantity", 0)
        for item in items
        if item.get("is_included") and item.get("type_id") == order.eve_type_id
    )
    price = Decimal(str(contract.get("price", 0)))

    if quantity < 1:
        return Verdict(
            Outcome.INVALID,
            reason_code=reasons.NO_ITEM,
            reason_data={"item": order.eve_type.name},
            order=order,
            share=share,
            price=price,
        )

    expected = order.unit_price * quantity
    if abs(price - expected) > PRICE_TOLERANCE:
        return Verdict(
            Outcome.INVALID,
            reason_code=reasons.WRONG_PRICE,
            reason_data={"expected": str(expected), "quantity": quantity},
            order=order,
            share=share,
            quantity=quantity,
            price=price,
        )

    pending_elsewhere = (
        share.contracts.filter(state=ContractRecord.State.OUTSTANDING)
        .exclude(contract_id=contract_id)
        .aggregate(total=Coalesce(Sum("quantity"), 0))["total"]
    )
    available = share.taken - share.credited - pending_elsewhere
    if quantity > available:
        return Verdict(
            Outcome.INVALID,
            reason_code=reasons.TOO_MANY,
            reason_data={"available": max(available, 0), "quantity": quantity},
            order=order,
            share=share,
            quantity=quantity,
            price=price,
        )

    outcome = Outcome.CREDIT if status == "finished" else Outcome.PENDING

    return Verdict(outcome, order=order, share=share, quantity=quantity, price=price)