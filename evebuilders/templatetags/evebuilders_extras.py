"""Template filters of the plugin"""

# Standard Library
from datetime import timezone as dt_timezone
from decimal import ROUND_HALF_UP, Decimal

# Django
from django import template
from django.contrib.humanize.templatetags.humanize import intcomma
from django.utils.html import format_html

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


@register.filter
def local_time(value, kind: str = "datetime") -> str:
    """
    A moment as a <time> element.

    The text is in UTC, for a browser without scripts. The script of the plugin
    replaces it with the time in the time zone of the browser and keeps the UTC
    text as the hint.

    :param kind: "datetime" for the date and the time, "time" for the time only
    """

    if not value:
        return ""

    utc = value.astimezone(dt_timezone.utc)
    pattern = "%H:%M UTC" if kind == "time" else "%Y-%m-%d %H:%M UTC"

    return format_html(
        '<time class="evb-local" data-kind="{}" datetime="{}">{}</time>',
        kind,
        utc.isoformat(),
        utc.strftime(pattern),
    )
