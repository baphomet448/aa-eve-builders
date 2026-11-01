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
        ("Взять заказ:", _order_list_url()),
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



def _settings_url() -> str:
    """The link to the plugin settings in Auth, empty if the site URL is not known"""

    site_url = str(getattr(settings, "SITE_URL", "")).rstrip("/")
    if not site_url:
        return ""

    return f"{site_url}{reverse('evebuilders:settings')}"


def _contract_lines(builder: str, quantity: int, price) -> list[str]:
    """The lines about a contract that every contract report starts with"""

    return [
        f"Отчет от - {builder}",
        f"Контракт на {quantity} позиций",
        f"Контракт {format_isk(price)} {isk_in_words(price)}",
    ]


def contract_waiting_payload(*, builder: str, order: Order, quantity: int, price) -> dict:
    """A valid contract waits for acceptance"""

    return build_payload(
        _contract_lines(builder, quantity, price),
        [
            ("Заказ", order.number),
            ("Наименование", order.eve_type.name),
            ("СТАТУС", "ОЖИДАЕТ ВАЛИДАЦИИ КОНТРАКТА"),
        ],
    )


def contract_credited_payload(
    *, builder: str, order: Order, quantity: int, price, acceptor: str, remaining: int
) -> dict:
    """A contract was accepted and credited

    :param acceptor: Who accepted the contract in the game
    :param remaining: How many items of the order are still not credited
    """

    lines = _contract_lines(builder, quantity, price)
    lines.append(f"Контракт принял - {acceptor}")
    if remaining <= 0:
        lines.append(f"Заказ завершен полностью - {order.quantity} шт")
    else:
        lines.append(f"Остаток по заказу - {remaining} шт")

    return build_payload(
        lines, [("Заказ", order.number), ("Наименование", order.eve_type.name)]
    )


def contract_invalid_payload(
    *, reporter: str, order: Order | None, quantity: int, price, reason: str
) -> dict:
    """A contract was found that cannot be counted

    :param reporter: Who made the contract
    :param order: The order the contract is for, if it is known
    """

    lines = [f"Отчет от - {reporter}", "Контракт не прошёл проверку и не засчитан"]
    if quantity > 0:
        lines.append(f"Контракт на {quantity} позиций")
        lines.append(f"Контракт {format_isk(price)} {isk_in_words(price)}")

    fields = []
    if order is not None:
        fields.append(("Заказ", order.number))
    fields.append(("Причина", reason))

    return build_payload(lines, fields)


def token_failure_payload(*, corporation: str, error: str) -> dict:
    """The ESI token stopped working"""

    url = _settings_url()
    what_to_do = "Подключите токен заново в настройках плагина (ESI connection)"
    if url:
        what_to_do += f": {url}"

    return build_payload(
        [
            "ESI-токен корпорации перестал работать",
            "Контракты не читаются, зачисления остановлены.",
        ],
        [("Корпорация", corporation), ("Причина", error), ("Что делать", what_to_do)],
    )

def taken_payload(*, user, order: Order, quantity: int, free: int) -> dict:
    """
    A builder took (a part of) an order.

    :param quantity: How many items were taken now
    :param free: How many items are still free in the order
    """

    total = order.unit_price * quantity

    return build_payload(
        [f"Заказ {order.number} отдан в работу - {display_name(user)}"],
        [
            ("Наименование", order.eve_type.name),
            ("Количество", str(quantity)),
            ("Остаток свободных позиций в заказе", str(free)),
            (
                "Цена за единицу",
                f"{format_isk(order.unit_price)} {isk_in_words(order.unit_price)}",
            ),
            ("Цена за все", f"{format_isk(total)} {isk_in_words(total)}"),
            ("Срок сдачи до", order.due_date.isoformat()),
        ],
    )