"""Numbers about the orders for the management: what was built, what is left to buy out"""

# Standard Library
from dataclasses import dataclass
from decimal import Decimal

# Django
from django.db.models import Sum
from django.db.models.functions import Coalesce

# AA EVE Builders
from evebuilders.models import Order, OrderAssignment
from evebuilders.orders import OPEN_STATUSES

# The category of the ships in EVE
SHIP_CATEGORY_ID = 6

# The classes in the order they are shown, with the EVE groups of each class.
# A ship of a group that is not listed here is counted as "other" (haulers,
# shuttles, capsules ...). Change a class here and nowhere else.
SHIP_CLASSES: dict[str, tuple[str, ...]] = {
    "frigates": (
        "Frigate",
        "Assault Frigate",
        "Covert Ops",
        "Electronic Attack Ship",
        "Expedition Frigate",
        "Interceptor",
        "Logistics Frigate",
        "Stealth Bomber",
    ),
    "destroyers": (
        "Destroyer",
        "Interdictor",
        "Tactical Destroyer",
        "Command Destroyer",
    ),
    "cruisers": (
        "Cruiser",
        "Heavy Assault Cruiser",
        "Heavy Interdiction Cruiser",
        "Logistics",
        "Force Recon Ship",
        "Combat Recon Ship",
        "Strategic Cruiser",
    ),
    "battlecruisers": (
        "Combat Battlecruiser",
        "Attack Battlecruiser",
        "Command Ship",
    ),
    "battleships": (
        "Battleship",
        "Black Ops",
        "Marauder",
    ),
    "capital": (
        "Carrier",
        "Command Carrier",
        "Dreadnought",
        "Lancer Dreadnought",
        "Force Auxiliary",
        "Supercarrier",
        "Titan",
        "Capital Industrial Ship",
        "Freighter",
        "Jump Freighter",
    ),
}
OTHER = "other"

_CLASS_OF_GROUP = {
    group: ship_class for ship_class, groups in SHIP_CLASSES.items() for group in groups
}


@dataclass(frozen=True)
class Statistics:
    """The numbers of the tab Statistics"""

    total_orders: int
    ships_built: int
    built_by_class: dict[str, int]
    active_orders: int
    buyout_cost: Decimal


def ship_class(group_name: str) -> str:
    """The class of a ship by the name of its EVE group"""

    return _CLASS_OF_GROUP.get(group_name, OTHER)


def ships_built_by_class() -> dict[str, int]:
    """
    How many ships were delivered and credited, by class. Every order counts,
    also a cancelled one: what was delivered was built.
    """

    built = {name: 0 for name in (*SHIP_CLASSES, OTHER)}

    rows = (
        OrderAssignment.objects.filter(
            order__eve_type__eve_group__eve_category_id=SHIP_CATEGORY_ID,
            credited__gt=0,
        )
        .values("order__eve_type__eve_group__name")
        .annotate(total=Sum("credited"))
    )
    for row in rows:
        built[ship_class(row["order__eve_type__eve_group__name"])] += row["total"]

    return built


def buyout_cost() -> Decimal:
    """
    What it costs to buy out the active orders: the price per unit times what is
    not delivered yet. It goes down as items are delivered.
    """

    orders = Order.objects.filter(status__in=OPEN_STATUSES).annotate(
        credited_total=Coalesce(Sum("assignments__credited"), 0)
    )

    return sum(
        (
            order.unit_price * max(order.quantity - order.credited_total, 0)
            for order in orders
        ),
        Decimal("0"),
    )


def collect_statistics() -> Statistics:
    """All the numbers of the tab Statistics"""

    built = ships_built_by_class()

    return Statistics(
        total_orders=Order.objects.exclude(status=Order.Status.CANCELLED).count(),
        ships_built=sum(built.values()),
        built_by_class=built,
        active_orders=Order.objects.filter(status__in=OPEN_STATUSES).count(),
        buyout_cost=buyout_cost(),
    )
