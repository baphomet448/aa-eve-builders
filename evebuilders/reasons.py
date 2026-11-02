"""Why a contract cannot be counted: codes with parameters, translated when shown"""

# Django
from django.utils import translation
from django.utils.translation import gettext as _

CLOSED = "closed"
NO_NUMBER = "no_number"
MANY_NUMBERS = "many_numbers"
UNKNOWN_ORDER = "unknown_order"
NOT_ON_ACCOUNT = "not_on_account"
NOT_TAKEN = "not_taken"
NO_ITEM = "no_item"
WRONG_PRICE = "wrong_price"
TOO_MANY = "too_many"
NOT_AVAILABLE = "not_available"
ORDER_CANCELLED = "order_cancelled"


def reason_text(code: str, data: dict | None = None) -> str:
    """
    The reason in the current language.

    :param code: One of the codes above
    :param data: The parameters of the reason, by name
    :return: The text, empty for no code or an unknown code
    """

    data = data or {}

    if code == CLOSED:
        return _("The contract is %(status)s.") % {"status": data.get("status", "")}

    if code == NO_NUMBER:
        return _("The contract title has no order number.")

    if code == MANY_NUMBERS:
        return _("The contract title has more than one order number.")

    if code == UNKNOWN_ORDER:
        return _("There is no order with the number %(number)s.") % {
            "number": data.get("number", "")
        }

    if code == NOT_ON_ACCOUNT:
        return _("The character that made the contract is not on an Auth account.")

    if code == NOT_TAKEN:
        return _("The builder has not taken this order.")

    if code == NO_ITEM:
        return _("The contract does not contain %(item)s.") % {
            "item": data.get("item", "")
        }

    if code == WRONG_PRICE:
        return _("The price must be %(expected)s ISK for %(quantity)s items.") % {
            "expected": data.get("expected", ""),
            "quantity": data.get("quantity", ""),
        }

    if code == TOO_MANY:
        return _(
            "Only %(available)s items are left to deliver, "
            "the contract has %(quantity)s."
        ) % {
            "available": data.get("available", ""),
            "quantity": data.get("quantity", ""),
        }

    if code == NOT_AVAILABLE:
        return _("The items are no longer available to deliver.")

    if code == ORDER_CANCELLED:
        return _("The order was cancelled.")

    return ""


def english(code: str, data: dict | None = None) -> str:
    """The reason in English, whatever language the request is in"""

    with translation.override("en"):
        return reason_text(code, data)


def reason_fields(code: str, data: dict | None = None) -> dict:
    """
    The fields of a contract record that hold a reason: the English text, the
    code and the parameters.
    """

    return {
        "reason": english(code, data),
        "reason_code": code,
        "reason_data": dict(data or {}),
    }