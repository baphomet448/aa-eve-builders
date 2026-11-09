"""Builder access levels: who is a builder and which level each one has"""

# Django
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext as _

# AA EVE Builders
from evebuilders.messages import display_name
from evebuilders.models import BuilderProfile, Order, OrderEvent
from evebuilders.orders import builder_level
from evebuilders.permissions import MANAGE_ACCESS

User = get_user_model()

ACCESS_CODENAMES = ("builder_access", "manage_access")


def builder_users():
    """
    The active users who may work with orders: they have the builder or manager
    access permission themselves, through a group or through their state, or
    they are superusers.
    """

    permissions = Permission.objects.filter(
        content_type__app_label="evebuilders", codename__in=ACCESS_CODENAMES
    )

    return (
        User.objects.filter(
            Q(is_superuser=True)
            | Q(user_permissions__in=permissions)
            | Q(groups__permissions__in=permissions)
            | Q(profile__state__permissions__in=permissions),
            is_active=True,
        )
        .select_related("profile__main_character")
        .distinct()
    )


def level_rows() -> list[dict]:
    """One row per builder for the levels page, sorted by name"""

    levels = dict(BuilderProfile.objects.values_list("user_id", "level"))

    rows = []
    for user in builder_users():
        main_character = user.profile.main_character
        rows.append(
            {
                "user": user,
                "name": display_name(user),
                "corporation": (
                    main_character.corporation_name if main_character else ""
                ),
                "level": levels.get(user.pk, Order.AccessLevel.BASE),
                "level_label": Order.AccessLevel(
                    levels.get(user.pk, Order.AccessLevel.BASE)
                ).label,
                "is_manager": user.has_perm(MANAGE_ACCESS),
            }
        )

    return sorted(rows, key=lambda row: row["name"].lower())


def set_builder_level(*, actor, user, level: int) -> bool:
    """
    Set the access level of a builder and write it to the history.

    :param actor: The manager who makes the change
    :param user: The builder
    :param level: One of Order.AccessLevel
    :raises django.core.exceptions.ValidationError: When the level is unknown
    :return: True if the level changed, False if the builder had it already
    """

    if level not in Order.AccessLevel.values:
        raise ValidationError(_("Unknown access level."))

    current = builder_level(user)
    if level == current:
        return False

    BuilderProfile.objects.update_or_create(user=user, defaults={"level": level})
    OrderEvent.objects.create(
        kind=OrderEvent.Kind.LEVEL_CHANGED,
        actor=actor,
        description=(
            f"Level of {display_name(user)}: "
            f"{Order.AccessLevel(current).label} -> {Order.AccessLevel(level).label}"
        ),
    )

    return True
