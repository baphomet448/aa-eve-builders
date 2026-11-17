"""The data of the order details page (managers only)"""

# Django
from django.db.models import Q

# Alliance Auth
from allianceauth.authentication.models import CharacterOwnership

# AA EVE Builders
from evebuilders.event_text import event_texts
from evebuilders.messages import display_name
from evebuilders.models import ContractRecord
from evebuilders.names import character_names
from evebuilders.orders import pending_quantity, releasable_quantity, share_status

EVENT_LIMIT = 100


def contract_choices(share) -> list:
    """
    The contracts a manager may close by crediting a share by hand: the
    contracts of the share that wait or are invalid, and the invalid contracts
    of the builder that belong to no order (for example one that was accepted
    without the order number in its title).
    """

    character_ids = list(
        CharacterOwnership.objects.filter(user=share.builder).values_list(
            "character__character_id", flat=True
        )
    )

    return list(
        ContractRecord.objects.filter(
            Q(
                assignment=share,
                state__in=[
                    ContractRecord.State.OUTSTANDING,
                    ContractRecord.State.INVALID,
                ],
            )
            | Q(
                order__isnull=True,
                state=ContractRecord.State.INVALID,
                issuer_character_id__in=character_ids,
            )
        ).order_by("-issued_at", "-created_at")
    )


def share_rows(order) -> list[dict]:
    """The builders of an order with their numbers and the contracts to pick"""

    shares = (
        order.assignments.filter(taken__gt=0)
        .select_related("builder__profile__main_character")
        .order_by("created_at")
    )

    return [
        {
            "share": share,
            "name": display_name(share.builder),
            "pending": pending_quantity(share),
            "open": releasable_quantity(share),
            "status": share_status(share),
            "contracts": contract_choices(share),
        }
        for share in shares
    ]


def contract_rows(order) -> list[dict]:
    """The contracts of an order, newest first, with names"""

    records = list(
        ContractRecord.objects.filter(order=order)
        .select_related("assignment__builder__profile__main_character")
        .order_by("-issued_at", "-created_at")
    )
    names = character_names(
        [r.issuer_character_id for r in records]
        + [r.acceptor_character_id for r in records if r.acceptor_character_id]
    )

    return [
        {
            "record": record,
            "builder": (
                display_name(record.assignment.builder)
                if record.assignment
                else names.get(record.issuer_character_id, record.issuer_character_id)
            ),
            "acceptor": names.get(
                record.acceptor_character_id, record.acceptor_character_id or ""
            ),
        }
        for record in records
    ]


def event_rows(order, limit: int = EVENT_LIMIT) -> list[dict]:
    """The newest events of an order with the names of the people and the texts"""

    events = list(
        order.events.select_related("actor__profile__main_character").order_by(
            "-created_at", "-pk"
        )[:limit]
    )
    texts = event_texts(events)

    return [
        {
            "event": event,
            "actor": display_name(event.actor) if event.actor else event.actor_label,
            "text": texts[event.pk],
        }
        for event in events
    ]
