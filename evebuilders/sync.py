"""Applying the verdicts about the corporation contracts to the orders"""

# Standard Library
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

# Django
from django.db import transaction
from django.db.models import Count, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext as _

# Alliance Auth
from allianceauth.eveonline.models import EveCharacter

# AA EVE Builders
from evebuilders.contracts import (
    EsiError,
    EsiTokenError,
    fetch_contract_items,
    fetch_corporation_contracts,
)
from evebuilders.matching import (
    Outcome,
    Verdict,
    classify_contract,
    user_of_character,
)
from evebuilders.models import (
    ContractRecord,
    ContractSource,
    Order,
    OrderAssignment,
    OrderEvent,
)
from evebuilders.orders import recalculate_status

logger = logging.getLogger(__name__)


@dataclass
class SyncReport:
    """What a contract sync did. Counts only what changed in this run."""

    seen: int = 0  # contracts in the ESI list
    pending: int = 0  # new or changed contracts that wait for acceptance
    credited: int = 0  # contracts that were credited
    credited_items: int = 0  # items credited by them
    closed: int = 0  # contracts that ended without success
    invalid: int = 0  # new or changed invalid contracts
    skipped: int = 0  # contracts that could not be checked (try again later)
    error: str = ""  # why the whole sync failed, empty if it did not
    expires: datetime | None = None  # until when ESI keeps this answer

    # The state right now, not what changed in this run
    waiting_contracts: int = 0  # contracts that wait for acceptance
    waiting_items: int = 0  # the items in those contracts
    problem_contracts: int = 0  # contracts that cannot be counted

    @property
    def changed(self) -> bool:
        """Whether this run changed anything"""

        return bool(self.pending or self.credited or self.closed or self.invalid)


def _money(value: Decimal) -> Decimal:
    """A price with two decimals, as stored"""

    return value.quantize(Decimal("0.01"))


def _character_label(character_id: int) -> str:
    """The name of a character if Auth knows it, otherwise its ID"""

    name = (
        EveCharacter.objects.filter(character_id=character_id)
        .values_list("character_name", flat=True)
        .first()
    )

    return name or str(character_id)


def _values(contract: dict, verdict: Verdict) -> dict:
    """The fields of a contract record that come from the contract and verdict"""

    return {
        "order": verdict.order,
        "assignment": verdict.share,
        "title": (contract.get("title") or "")[:255],
        "issuer_character_id": contract.get("issuer_id") or 0,
        "quantity": verdict.quantity,
        "price": _money(verdict.price),
        "esi_status": contract.get("status") or "",
        "issued_at": parse_datetime(contract.get("date_issued") or ""),
    }


def _add_event(record: ContractRecord, kind: str, description: str) -> None:
    """Write a history entry. Contracts without a known order have no history."""

    if record.order is None:
        return

    OrderEvent.objects.create(
        order=record.order,
        assignment=record.assignment,
        kind=kind,
        description=description,
    )


def _apply_pending(contract: dict, verdict: Verdict) -> bool:
    """Record a valid contract that waits for acceptance. Returns True if it changed."""

    values = _values(contract, verdict)

    with transaction.atomic():
        record, created = ContractRecord.objects.select_for_update().get_or_create(
            contract_id=contract["contract_id"],
            defaults={**values, "state": ContractRecord.State.OUTSTANDING},
        )
        changed = created

        if not created:
            changed = (
                record.state != ContractRecord.State.OUTSTANDING
                or record.quantity != verdict.quantity
            )
            for field, value in values.items():
                setattr(record, field, value)
            record.state = ContractRecord.State.OUTSTANDING
            record.reason = ""
            record.save()

        if changed:
            _add_event(
                record,
                OrderEvent.Kind.CONTRACT_FOUND,
                f"Contract {record.contract_id} with {record.quantity} items "
                "waits for acceptance",
            )

    return changed


def _apply_invalid(contract: dict, verdict: Verdict) -> bool:
    """Record a contract that cannot be counted. Returns True if it changed."""

    values = _values(contract, verdict)

    with transaction.atomic():
        record, created = ContractRecord.objects.select_for_update().get_or_create(
            contract_id=contract["contract_id"],
            defaults={
                **values,
                "state": ContractRecord.State.INVALID,
                "reason": verdict.reason,
            },
        )
        changed = created

        if not created:
            if record.state == ContractRecord.State.CREDITED:
                return False

            changed = (
                record.state != ContractRecord.State.INVALID
                or record.reason != verdict.reason
            )
            for field, value in values.items():
                setattr(record, field, value)
            record.state = ContractRecord.State.INVALID
            record.reason = verdict.reason
            record.save()

        if changed:
            _add_event(
                record,
                OrderEvent.Kind.CONTRACT_INVALID,
                f"Contract {record.contract_id} cannot be counted: {verdict.reason}",
            )

    return changed


def _apply_closed(contract: dict, verdict: Verdict) -> bool:
    """A known contract ended without success. Returns True if it changed."""

    with transaction.atomic():
        record = (
            ContractRecord.objects.select_for_update()
            .filter(contract_id=contract["contract_id"])
            .first()
        )
        if record is None or record.state in (
            ContractRecord.State.CLOSED,
            ContractRecord.State.CREDITED,
        ):
            return False

        record.state = ContractRecord.State.CLOSED
        record.reason = verdict.reason
        record.esi_status = contract.get("status") or ""
        record.save()
        _add_event(
            record,
            OrderEvent.Kind.CONTRACT_CLOSED,
            f"Contract {record.contract_id} ended without being accepted "
            f"({record.esi_status})",
        )

    return True


def _apply_credit(contract: dict, verdict: Verdict, now) -> int:
    """
    Count an accepted contract. Returns the number of items credited (0 if
    nothing was credited).

    The order is locked first and then the share, as when taking and giving
    back, so these operations cannot block each other for good.
    """

    values = _values(contract, verdict)

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=verdict.order.pk)
        share = OrderAssignment.objects.select_for_update().get(pk=verdict.share.pk)
        record, _created = ContractRecord.objects.select_for_update().get_or_create(
            contract_id=contract["contract_id"],
            defaults={**values, "state": ContractRecord.State.OUTSTANDING},
        )

        if record.state == ContractRecord.State.CREDITED:
            return 0

        waiting_elsewhere = (
            share.contracts.filter(state=ContractRecord.State.OUTSTANDING)
            .exclude(pk=record.pk)
            .aggregate(total=Coalesce(Sum("quantity"), 0))["total"]
        )
        available = share.taken - share.credited - waiting_elsewhere

        for field, value in values.items():
            setattr(record, field, value)

        if verdict.quantity > available:
            # Things changed since the verdict was made (e.g. items were given back)
            record.state = ContractRecord.State.INVALID
            record.reason = _("The items are no longer available to deliver.")
            record.save()
            _add_event(
                record,
                OrderEvent.Kind.CONTRACT_INVALID,
                f"Contract {record.contract_id} cannot be counted: {record.reason}",
            )

            return 0

        acceptor_id = contract.get("acceptor_id") or None
        record.acceptor_character_id = acceptor_id
        record.acceptor_user = user_of_character(acceptor_id) if acceptor_id else None
        record.completed_at = parse_datetime(contract.get("date_completed") or "") or now
        record.state = ContractRecord.State.CREDITED
        record.reason = ""
        record.save()

        share.credited += verdict.quantity
        share.save(update_fields=["credited", "updated_at"])

        accepted_by = _character_label(acceptor_id) if acceptor_id else "unknown"
        _add_event(
            record,
            OrderEvent.Kind.CREDITED,
            f"Credited {verdict.quantity} x {order.eve_type.name} "
            f"(contract {record.contract_id}), accepted by {accepted_by}",
        )
        recalculate_status(order)

    return verdict.quantity


def process_contracts(
    contracts: list, *, corporation_id: int, items_loader, now=None
) -> SyncReport:
    """
    Apply what the contracts mean to the orders.

    Contracts are processed from the oldest to the newest, so when a builder
    has more contracts than items left, the older ones win.

    :param contracts: The ESI list of corporation contracts
    :param corporation_id: The corporation the orders are for
    :param items_loader: Returns the ESI items of a contract
    :param now: The current time (for tests)
    :raises EsiTokenError: When the token stops working while reading items
    :return: What changed
    """

    now = now or timezone.now()
    report = SyncReport()

    ordered = sorted(
        contracts,
        key=lambda c: (c.get("date_issued") or "", c.get("contract_id") or 0),
    )

    for contract in ordered:
        report.seen += 1

        try:
            verdict = classify_contract(
                contract,
                corporation_id=corporation_id,
                items_loader=items_loader,
                now=now,
            )
        except EsiTokenError:
            raise
        except EsiError as ex:
            logger.warning(
                "Contract %s could not be checked: %s", contract.get("contract_id"), ex
            )
            report.skipped += 1
            continue

        if verdict.outcome is Outcome.PENDING:
            report.pending += _apply_pending(contract, verdict)
        elif verdict.outcome is Outcome.CREDIT:
            items = _apply_credit(contract, verdict, now)
            if items:
                report.credited += 1
                report.credited_items += items
        elif verdict.outcome is Outcome.CLOSED:
            report.closed += _apply_closed(contract, verdict)
        elif verdict.outcome is Outcome.INVALID:
            report.invalid += _apply_invalid(contract, verdict)

    return report


def _record_failure(source: ContractSource, error: str, token_ok: bool | None) -> None:
    """Remember on the source that a sync failed"""

    changes = {"last_sync_at": timezone.now(), "last_error": error[:1000]}
    if token_ok is not None:
        changes["token_ok"] = token_ok

    ContractSource.objects.filter(pk=source.pk).update(**changes)


def sync_contracts(source: ContractSource | None = None) -> SyncReport:
    """
    Read the corporation contracts from ESI and apply them to the orders.

    Problems are not raised but returned in the report and remembered on the
    source, so scheduled runs and buttons can show them.

    :param source: The ESI source, the connected one by default
    :return: What the sync did
    """

    source = source or ContractSource.get_solo()
    if source is None:
        return SyncReport(error=_("No ESI source is connected."))

    def load_items(contract_id: int) -> list:
        return fetch_contract_items(source, contract_id)

    try:
        fetched = fetch_corporation_contracts(source)
        report = process_contracts(
            fetched.contracts,
            corporation_id=source.corporation_id,
            items_loader=load_items,
        )
    except EsiTokenError as ex:
        _record_failure(source, str(ex), token_ok=False)

        return SyncReport(error=str(ex))
    except EsiError as ex:
        _record_failure(source, str(ex), token_ok=None)

        return SyncReport(error=str(ex))

    report.expires = fetched.expires
    _fill_current_state(report)
    now = timezone.now()
    ContractSource.objects.filter(pk=source.pk).update(
        last_sync_at=now, last_success_at=now, last_error="", token_ok=True
    )

    return report

def _fill_current_state(report: SyncReport) -> None:
    """Put the current numbers of waiting and problem contracts into the report"""

    waiting = ContractRecord.objects.filter(
        state=ContractRecord.State.OUTSTANDING
    ).aggregate(contracts=Count("pk"), items=Coalesce(Sum("quantity"), 0))

    report.waiting_contracts = waiting["contracts"]
    report.waiting_items = waiting["items"]
    report.problem_contracts = ContractRecord.objects.filter(
        state=ContractRecord.State.INVALID
    ).count()