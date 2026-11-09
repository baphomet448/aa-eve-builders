"""Template filters of the plugin"""

# Standard Library
from decimal import ROUND_HALF_UP, Decimal

# Django
from django import template

register = template.Library()


@register.filter
def plain_isk(value) -> str:
    """
    An amount as whole ISK without separators, ready to be pasted into the
    game: 1500000
    """

    if value is None or value == "":
        return ""

    return str(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
