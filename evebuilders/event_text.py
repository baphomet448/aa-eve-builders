"""The texts of the history in the language of the reader

The history keeps the text of an event as it was written, in English. A page
translates the texts that the plugin writes itself and puts the numbers in order.
What a person typed (the reason of a deletion, a comment) is shown as it was typed.
"""

# Standard Library
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Django
from django.contrib.humanize.templatetags.humanize import intcomma
from django.utils.translation import gettext as _

# AA EVE Builders
from evebuilders.models import ContractRecord, OrderEvent

Kind = OrderEvent.Kind

# The fields in the text of a change of an order, as the plugin writes them
_FIELDS = (
    "item",
    "quantity",
    "price per unit",
    "priority",
    "due date",
    "access level",
    "destination",
    "note",
)
_FIELD_NAMES = "|".join(re.escape(name) for name in _FIELDS)
_CHANGE = re.compile(
    rf"(?P<field>{_FIELD_NAMES}): (?P<old>.*?) -> (?P<new>.*?)"
    rf"(?=; (?:{_FIELD_NAMES}): |$)",
    re.DOTALL,
)
_CONTRACT_AT_START = re.compile(r"^Contract (\d+) ")


def _number(value: str) -> str:
    """A whole number with the separators of the language"""

    return intcomma(int(value)) if value.isdigit() else value


def _isk(value: str) -> str:
    """An amount in whole ISK with the separators of the language"""

    try:
        whole = Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return value

    return intcomma(int(whole))


def _field(name: str) -> str:
    """The name of a field of an order in the language of the reader"""

    return {
        "item": _("item"),
        "quantity": _("quantity"),
        "price per unit": _("price per unit"),
        "priority": _("priority"),
        "due date": _("due date"),
        "access level": _("access level"),
        "destination": _("destination"),
        "note": _("note"),
    }[name]


def _value(text: str) -> str:
    """A value of a changed field: only "nothing" needs a translation"""

    return _("(empty)") if text == "(empty)" else text


def _created(g: dict, records: dict) -> str:
    return _("%(quantity)s × %(item)s, %(price)s ISK each") % {
        "quantity": _number(g["quantity"]),
        "item": g["item"],
        "price": _isk(g["price"]),
    }


def _taken(g: dict, records: dict) -> str:
    return _("Took %(quantity)s (now %(total)s in total)") % {
        "quantity": _number(g["quantity"]),
        "total": _number(g["total"]),
    }


def _discarded(g: dict, records: dict) -> str:
    return _("Gave back %(quantity)s (now %(total)s in total)") % {
        "quantity": _number(g["quantity"]),
        "total": _number(g["total"]),
    }


def _released(g: dict, records: dict) -> str:
    return _("Released %(quantity)s from %(builder)s (now %(total)s in total)") % {
        "quantity": _number(g["quantity"]),
        "builder": g["builder"],
        "total": _number(g["total"]),
    }


def _found(g: dict, records: dict) -> str:
    return _("Contract %(contract)s with %(quantity)s items waits for acceptance") % {
        "contract": g["contract"],
        "quantity": _number(g["quantity"]),
    }


def _invalid(g: dict, records: dict) -> str:
    reason = g["reason"]
    record = records.get(int(g["contract"]))
    # The reason of the record can be shown in the language of the reader. It is
    # taken only when it is the very reason that was written to the history.
    if record is not None and record.reason == reason:
        reason = record.reason_text

    return _("Contract %(contract)s cannot be counted: %(reason)s") % {
        "contract": g["contract"],
        "reason": reason,
    }


def _closed(g: dict, records: dict) -> str:
    return _("Contract %(contract)s ended without being accepted (%(status)s)") % {
        "contract": g["contract"],
        "status": g["status"],
    }


def _credited(g: dict, records: dict) -> str:
    who = _("unknown") if g["who"] == "unknown" else g["who"]

    return _(
        "Delivered %(quantity)s × %(item)s (contract %(contract)s), "
        "accepted by %(who)s"
    ) % {
        "quantity": _number(g["quantity"]),
        "item": g["item"],
        "contract": g["contract"],
        "who": who,
    }


def _manual(g: dict, records: dict) -> str:
    text = _("Credited manually %(quantity)s × %(item)s") % {
        "quantity": _number(g["quantity"]),
        "item": g["item"],
    }
    if g["contract"]:
        text += " (" + _("contract %(contract)s") % {"contract": g["contract"]} + ")"
    if g["comment"]:
        text += f": {g['comment']}"

    return text


def _updated(g: dict, records: dict) -> str:
    changes = []
    for match in _CHANGE.finditer(g["changes"]):
        field, old, new = match["field"], match["old"], match["new"]
        if field == "price per unit":
            old, new = _isk(old), _isk(new)
        elif field == "quantity":
            old, new = _number(old), _number(new)
        changes.append(f"{_field(field)}: {_value(old)} → {_value(new)}")

    if not changes:
        return ""

    return _("Order changed: %(changes)s") % {"changes": "; ".join(changes)}


def _cancelled(g: dict, records: dict) -> str:
    text = _("Order cancelled")
    if g["reason"]:
        text += f": {g['reason']}"

    return text


def _level(g: dict, records: dict) -> str:
    return _("Level of %(name)s: %(old)s → %(new)s") % g


def _role(g: dict, records: dict) -> str:
    roles = {"Builder": _("Builder"), "Manager": _("Manager")}

    return _("Role of %(name)s: %(old)s → %(new)s") % {
        "name": g["name"],
        "old": roles[g["old"]],
        "new": roles[g["new"]],
    }


# The kind of an event, the text the plugin writes for it, and what shows it
_ENTRIES = {
    Kind.CREATED: (
        re.compile(
            r"^(?P<quantity>\d+) x (?P<item>.+), (?P<price>\S+) ISK each$", re.DOTALL
        ),
        _created,
    ),
    Kind.TAKEN: (
        re.compile(r"^Took (?P<quantity>\d+) \(now (?P<total>\d+) in total\)$"),
        _taken,
    ),
    Kind.DISCARDED: (
        re.compile(r"^Gave back (?P<quantity>\d+) \(now (?P<total>\d+) in total\)$"),
        _discarded,
    ),
    Kind.RELEASED: (
        re.compile(
            r"^Released (?P<quantity>\d+) from (?P<builder>.+) "
            r"\(now (?P<total>\d+) in total\)$"
        ),
        _released,
    ),
    Kind.CONTRACT_FOUND: (
        re.compile(
            r"^Contract (?P<contract>\d+) with (?P<quantity>\d+) items "
            r"waits for acceptance$"
        ),
        _found,
    ),
    Kind.CONTRACT_INVALID: (
        re.compile(
            r"^Contract (?P<contract>\d+) cannot be counted: (?P<reason>.*)$",
            re.DOTALL,
        ),
        _invalid,
    ),
    Kind.CONTRACT_CLOSED: (
        re.compile(
            r"^Contract (?P<contract>\d+) ended without being accepted "
            r"\((?P<status>.*)\)$"
        ),
        _closed,
    ),
    Kind.CREDITED: (
        re.compile(
            r"^Credited (?P<quantity>\d+) x (?P<item>.+) "
            r"\(contract (?P<contract>\d+)\), accepted by (?P<who>.+)$"
        ),
        _credited,
    ),
    Kind.MANUAL_CREDIT: (
        re.compile(
            r"^Credited (?P<quantity>\d+) x (?P<item>.+?) manually"
            r"(?: \(contract (?P<contract>\d+)\))?(?:: (?P<comment>.*))?$",
            re.DOTALL,
        ),
        _manual,
    ),
    Kind.UPDATED: (
        re.compile(r"^Order changed: (?P<changes>.+)$", re.DOTALL),
        _updated,
    ),
    Kind.CANCELLED: (
        re.compile(r"^Order cancelled(?:: (?P<reason>.*))?$", re.DOTALL),
        _cancelled,
    ),
    Kind.LEVEL_CHANGED: (
        re.compile(r"^Level of (?P<name>.+): (?P<old>\w+) -> (?P<new>\w+)$"),
        _level,
    ),
    Kind.ROLE_CHANGED: (
        re.compile(
            r"^Role of (?P<name>.+): (?P<old>Builder|Manager) -> "
            r"(?P<new>Builder|Manager)$"
        ),
        _role,
    ),
}


def describe(event: OrderEvent, records: dict | None = None) -> str:
    """
    The text of an event in the language of the reader. A text that the plugin
    does not know stays as it was written.

    :param records: The contract records by contract ID, for the reasons of the
        events about contracts that cannot be counted
    """

    entry = _ENTRIES.get(event.kind)
    if entry is not None:
        pattern, render = entry
        match = pattern.match(event.description)
        if match is not None:
            text = render(match.groupdict(), records or {})
            if text:
                return text

    return event.description


def event_texts(events: list) -> dict[int, str]:
    """The texts of events in the language of the reader, by the ID of the event"""

    contract_ids = {
        int(match.group(1))
        for event in events
        if event.kind == Kind.CONTRACT_INVALID
        and (match := _CONTRACT_AT_START.match(event.description))
    }
    records = (
        {
            record.contract_id: record
            for record in ContractRecord.objects.filter(contract_id__in=contract_ids)
        }
        if contract_ids
        else {}
    )

    return {event.pk: describe(event, records) for event in events}
