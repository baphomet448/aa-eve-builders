"""The texts of the Discord notifications (Russian, as in the live system)"""

# Django
from django.conf import settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.models import Order
from evebuilders.notifications import build_payload, format_isk, isk_in_words


def display_name(user) -> str:
    """The name used in reports: the main character, otherwise the login"""

    main_character = user.profile.main_character

    return main_character.character_name if main_character else user.username


def _order_list_url() -> str:
    """The link to the order list in Auth, empty if the site URL is not known"""

    site_url = str(getattr(settings, "SITE_URL", "")).rstrip("/")
    if not site_url:
        return ""

    return f"{site_url}{reverse('evebuilders:orders')}"


def new_order_payload(order: Order) -> dict:
    """The message about a new order"""

    fields = [
        ("Заказ", order.number),
        ("Наименование", order.eve_type.name),
        ("Количество", str(order.quantity)),
        ("Цена за единицу", format_isk(order.unit_price)),
        ("Приоритет", order.priority),
        ("Оснастка", _order_list_url()),
        ("Срок сдачи до", order.due_date.isoformat()),
    ]
    if order.access_level != Order.AccessLevel.BASE:
        fields.append(("Уровень доступа", order.get_access_level_display()))

    return build_payload(fields=fields)


def discard_payload(*, user, order: Order, quantity: int, free: int) -> dict:
    """
    The message about a builder giving items back.

    :param quantity: How many items were given back
    :param free: How many items are free in the order now
    """

    total = order.unit_price * quantity

    return build_payload(
        [
            f"Отчет от - {display_name(user)}",
            f"Отказ от {quantity} позиций",
            f"Сумма {format_isk(total)} {isk_in_words(total)}",
            "ОТМЕНА",
        ],
        [
            ("Заказ", f"{order.number} - Отменен"),
            ("Наименование", order.eve_type.name),
            ("Свободно в заказе", f"{free} шт"),
        ],
    )