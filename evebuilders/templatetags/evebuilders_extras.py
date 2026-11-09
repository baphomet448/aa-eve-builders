"""Template filters of the plugin"""

# Standard Library
from decimal import ROUND_HALF_UP, Decimal

# Django
from django import template
from django.contrib.humanize.templatetags.humanize import intcomma

register = template.Library()


def _whole(value) -> int:
    """An amount rounded to whole ISK"""

    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@register.filter
def plain_isk(value) -> str:
    """
    An amount as whole ISK without separators, ready to be pasted into the
    game: 1500000
    """

    if value is None or value == "":
        return ""

    return str(_whole(value))


@register.filter
def isk(value) -> str:
    """An amount in whole ISK with thousands separators: 1,500,000"""

    if value is None or value == "":
        return ""

    return intcomma(_whole(value))
