"""The data of the Management page (managers only)"""

# Alliance Auth
from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter

# AA EVE Builders
from evebuilders.messages import display_name
from evebuilders.models import ContractRecord, OrderAssignment, OrderEvent
from evebuilders.orders import OPEN_STATUSES

LIST_LIMIT = 100
EVENT_LIMIT = 50


def _names(character_ids) -> dict:
    """Names of the characters Auth knows, by character ID"""

    return dict(
        EveCharacter.objects.filter(character_id__in=set(character_ids)).values_list(
            "character_id", "character_name"
        )
    )


def problem_contract_rows(limit: int = LIST_LIMIT) -> list[dict]:
    """
    Contracts that were found but cannot be counted, newest first.

    Each row has the orders to look at: the order of the contract if it has
    one, otherwise the open orders the builder who made the contract has taken.
    """

    records = list(
        ContractRecord.objects.filter(state=ContractRecord.State.INVALID)
        .select_related("order__eve_type")
        .order_by("-issued_at", "-created_at")[:limit]
    )
    issuer_ids = {record.issuer_character_id for record in records}
    names = _names(issuer_ids)
    owners = dict(
        CharacterOwnership.objects.filter(
            character__character_id__in=issuer_ids
        ).values_list("character__character_id", "user_id")
    )

    open_orders: dict[int, list] = {}
    shares = (
        OrderAssignment.objects.filter(
            builder_id__in=set(owners.values()),
            taken__gt=0,
            order__status__in=OPEN_STATUSES,
        )
        .select_related("order__eve_type")
        .order_by("-order__created_at")
    )
    for share in shares:
        open_orders.setdefault(share.builder_id, []).append(share.order)

    return [
        {
            "record": record,
            "issuer": names.get(record.issuer_character_id, record.issuer_character_id),
            "orders": (
                [record.order]
                if record.order is not None
                else open_orders.get(owners.get(record.issuer_character_id), [])
            ),
        }
        for record in records
    ]


def waiting_contract_rows(limit: int = LIST_LIMIT) -> list[dict]:
    """Valid contracts that wait for acceptance in the game, newest first"""

    records = (
        ContractRecord.objects.filter(state=ContractRecord.State.OUTSTANDING)
        .select_related("order__eve_type", "assignment__builder__profile__main_character")
        .order_by("-issued_at", "-created_at")[:limit]
    )

    return [
        {
            "record": record,
            "builder": display_name(record.assignment.builder)
            if record.assignment
            else "",
        }
        for record in records
    ]


def recent_events(limit: int = EVENT_LIMIT) -> list[dict]:
    """The newest events of all orders (and the ones that belong to none)"""

    events = OrderEvent.objects.select_related(
        "order", "actor__profile__main_character"
    ).order_by("-created_at", "-pk")[:limit]

    return [
        {"event": event, "actor": display_name(event.actor) if event.actor else ""}
        for event in events
    ]