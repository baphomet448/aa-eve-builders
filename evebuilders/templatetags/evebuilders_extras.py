"""Template filters of the plugin"""

# Standard Library
from datetime import timezone as dt_timezone
from decimal import ROUND_HALF_UP, Decimal

# Django
from django import template
from django.contrib.humanize.templatetags.humanize import intcomma
from django.utils.html import format_html

# AA EVE Builders
from evebuilders.models import ContractSource
from evebuilders.orders import recipient_name
from evebuilders.permissions import has_any_access, is_admin, is_manager
from evebuilders.statistics import buyout_cost

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


@register.filter
def can_access(user) -> bool:
    """Whether the user has any role of the plugin"""

    return has_any_access(user)


@register.filter
def can_manage(user) -> bool:
    """Whether the user is a manager or an admin"""

    return is_manager(user)


@register.filter
def can_administer(user) -> bool:
    """Whether the user is an admin"""

    return is_admin(user)


@register.simple_tag(takes_context=True)
def order_recipient(context, order) -> str:
    """
    Who the items of an order are delivered to: the same name that the page My orders
    shows. The connection is read once for a whole page.
    """

    render_context = context.render_context
    if "evebuilders_source" not in render_context:
        render_context["evebuilders_source"] = ContractSource.get_solo()

    return recipient_name(order, render_context["evebuilders_source"])


@register.simple_tag
def active_buyout_cost():
    """What it costs to buy out the active orders (the same sum the statistics had)"""

    return buyout_cost()
