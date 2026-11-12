"""The texts of the Discord notifications (Russian, as in the live system)"""

# Django
from django.conf import settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.models import Order
from evebuilders.notifications import (
    EMOJI_CHANGED,
    EMOJI_CREDITED,
    EMOJI_CREDITED_BY_HAND,
    EMOJI_DELETED,
    EMOJI_GIVEN_BACK,
    EMOJI_INVALID,
    EMOJI_NEW,
    EMOJI_TAKEN,
    EMOJI_WAITING,
    EMOJI_WARNING,
    KIND_CONTRACT_CREDITED,
    KIND_CONTRACT_INVALID,
    KIND_CONTRACT_WAITING,
    KIND_GIVEN_BACK,
    KIND_MANUAL_CREDIT,
    KIND_NEW_ORDER,
    KIND_ORDER_CANCELLED,
    KIND_ORDER_CHANGED,
    KIND_RELEASED,
    KIND_TAKEN,
    KIND_TOKEN_FAILURE,
    build_payload,
    format_isk,
    isk_in_words,
    message_of,
    positions_for,
    positions_of,
)


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


@message_of(KIND_NEW_ORDER, EMOJI_NEW)
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
        ("Доставка", order.destination),
    ]
    if order.access_level != Order.AccessLevel.BASE:
        fields.append(("Уровень доступа", order.get_access_level_display()))

    return build_payload(fields=fields)


@message_of(KIND_GIVEN_BACK, EMOJI_GIVEN_BACK)
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
            f"Отказ от {positions_of(quantity)}",
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
        f"Контракт на {positions_for(quantity)}",
        f"Контракт {format_isk(price)} {isk_in_words(price)}",
    ]


@message_of(KIND_CONTRACT_WAITING, EMOJI_WAITING)
def contract_waiting_payload(
    *, builder: str, order: Order, quantity: int, price
) -> dict:
    """A valid contract waits for acceptance"""

    return build_payload(
        _contract_lines(builder, quantity, price),
        [
            ("Заказ", order.number),
            ("Наименование", order.eve_type.name),
            ("СТАТУС", "ОЖИДАЕТ ВАЛИДАЦИИ КОНТРАКТА"),
        ],
    )


@message_of(KIND_CONTRACT_CREDITED, EMOJI_CREDITED)
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


@message_of(KIND_CONTRACT_INVALID, EMOJI_INVALID)
def contract_invalid_payload(
    *, reporter: str, order: Order | None, quantity: int, price, reason: str
) -> dict:
    """A contract was found that cannot be counted

    :param reporter: Who made the contract
    :param order: The order the contract is for, if it is known
    """

    lines = [f"Отчет от - {reporter}", "Контракт не прошёл проверку и не засчитан"]
    if quantity > 0:
        lines.append(f"Контракт на {positions_for(quantity)}")
        lines.append(f"Контракт {format_isk(price)} {isk_in_words(price)}")

    fields = []
    if order is not None:
        fields.append(("Заказ", order.number))
    fields.append(("Причина", reason))

    return build_payload(lines, fields)


@message_of(KIND_TOKEN_FAILURE, EMOJI_WARNING)
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


@message_of(KIND_TAKEN, EMOJI_TAKEN)
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


@message_of(KIND_RELEASED, EMOJI_GIVEN_BACK)
def released_payload(
    *, manager, builder, order: Order, quantity: int, free: int
) -> dict:
    """A manager took items back from a builder

    :param quantity: How many items were taken back
    :param free: How many items are free in the order now
    """

    total = order.unit_price * quantity

    return build_payload(
        [
            f"Отчет от - {display_name(builder)}",
            f"Менеджер {display_name(manager)} снял с исполнителя "
            f"{positions_for(quantity)}",
            f"Сумма {format_isk(total)} {isk_in_words(total)}",
            "ОТМЕНА",
        ],
        [
            ("Заказ", f"{order.number} - Освобождено"),
            ("Наименование", order.eve_type.name),
            ("Свободно в заказе", f"{free} шт"),
        ],
    )


@message_of(KIND_MANUAL_CREDIT, EMOJI_CREDITED_BY_HAND)
def manual_credit_payload(
    *,
    manager,
    builder,
    order: Order,
    quantity: int,
    remaining: int,
    comment: str = "",
) -> dict:
    """A manager counted items as delivered by hand

    :param remaining: How many items of the order are still not credited
    """

    total = order.unit_price * quantity
    lines = [
        f"Отчет от - {display_name(builder)}",
        f"Зачтено вручную - {quantity} шт",
        f"Сумма {format_isk(total)} {isk_in_words(total)}",
        f"Зачёл - {display_name(manager)}",
    ]
    if comment:
        lines.append(f"Комментарий - {comment}")
    if remaining <= 0:
        lines.append(f"Заказ завершен полностью - {order.quantity} шт")
    else:
        lines.append(f"Остаток по заказу - {remaining} шт")

    return build_payload(
        lines, [("Заказ", order.number), ("Наименование", order.eve_type.name)]
    )


# The fields a manager may change on an order: (name in the history, name in Discord)
FIELD_LABELS = {
    "eve_type": ("item", "Наименование"),
    "quantity": ("quantity", "Количество"),
    "unit_price": ("price per unit", "Цена"),
    "priority": ("priority", "Приоритет"),
    "due_date": ("due date", "Срок сдачи"),
    "access_level": ("access level", "Уровень доступа"),
    "destination": ("destination", "Доставка"),
    "note": ("note", "Примечание"),
}


def show_value(field: str, value, empty: str = "<пусто>") -> str:
    """A value of an order field as plain text, for the history and for Discord"""

    if value is None or value == "":
        return empty
    if field == "eve_type":
        return value.name
    if field == "access_level":
        return Order.AccessLevel(value).label
    if field == "unit_price":
        return format(value.normalize(), "f")  # 1000000, not 1000000.00 or 1E+6
    if field == "due_date":
        return value.isoformat()

    return str(value)


@message_of(KIND_ORDER_CHANGED, EMOJI_CHANGED)
def order_changed_payload(*, manager, order: Order, changes) -> dict:
    """
    The message about a changed order.

    :param changes: Objects with ``field``, ``old`` and ``new``
    """

    return build_payload(
        [
            f"Заказ {order.number} был изменен {display_name(manager)}",
            "Измененные поля:",
        ],
        [
            (
                FIELD_LABELS[change.field][1],
                f"{show_value(change.field, change.old)} -> "
                f"{show_value(change.field, change.new)}",
            )
            for change in changes
        ],
    )


@message_of(KIND_ORDER_CANCELLED, EMOJI_DELETED)
def order_cancelled_payload(
    *, manager, order: Order, taken: int, reason: str = ""
) -> dict:
    """An order was deleted (cancelled)

    :param taken: How many items builders had taken
    :param reason: Why, if the manager said
    """

    fields = [
        ("Наименование", order.eve_type.name),
        ("Количество", str(order.quantity)),
    ]
    if taken:
        fields.append(("Было взято в работу", f"{taken} шт"))
    if reason:
        fields.append(("Причина", reason))

    return build_payload(
        [f"Заказ {order.number} был удален {display_name(manager)}"], fields
    )
