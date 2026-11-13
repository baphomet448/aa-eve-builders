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
from evebuilders.permissions import (
    CODENAMES,
    MANAGER_CODENAME,
    ROLE_ADMIN,
    ROLE_BUILDER,
    ROLE_MANAGER,
    is_manager,
    plugin_permissions,
    role_of,
)

User = get_user_model()

ACCESS_CODENAMES = CODENAMES


def builder_users():
    """
    The active users who may work with orders: they have a permission of the
    plugin themselves, through a group or through their state. Being a
    superuser is not enough.
    """

    permissions = Permission.objects.filter(
        content_type__app_label="evebuilders", codename__in=ACCESS_CODENAMES
    )

    return (
        User.objects.filter(
            Q(user_permissions__in=permissions)
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
        level = levels.get(user.pk, Order.AccessLevel.BASE)
        role = role_of(user)
        manager_direct, manager_via = manager_sources(user)
        rows.append(
            {
                "user": user,
                "name": display_name(user),
                "corporation": (
                    main_character.corporation_name if main_character else ""
                ),
                "level": level,
                "level_label": Order.AccessLevel(level).label,
                "is_manager": is_manager(user),
                "role": role,
                "role_rank": ROLE_RANKS.get(role, 0),
                "manager_direct": manager_direct,
                "manager_via": manager_via,
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


# The roles from the lowest to the highest, for sorting
ROLE_RANKS = {ROLE_BUILDER: 1, ROLE_MANAGER: 2, ROLE_ADMIN: 3}


def manager_sources(user) -> tuple[bool, str]:
    """
    Where the permission of a manager comes from.

    :return: Whether it is given to the user himself, and the names of the groups
        and the state that give it (joined by commas, empty if there are none)
    """

    if MANAGER_CODENAME not in plugin_permissions(user):
        return False, ""

    direct = user.user_permissions.filter(
        content_type__app_label="evebuilders", codename=MANAGER_CODENAME
    ).exists()

    names = list(
        user.groups.filter(
            permissions__content_type__app_label="evebuilders",
            permissions__codename=MANAGER_CODENAME,
        ).values_list("name", flat=True)
    )

    state = getattr(getattr(user, "profile", None), "state", None)
    if (
        state is not None
        and state.permissions.filter(
            content_type__app_label="evebuilders", codename=MANAGER_CODENAME
        ).exists()
    ):
        names.append(state.name)

    return direct, ", ".join(names)


def set_manager_role(*, actor, user, manager: bool) -> bool:
    """
    Make a builder a manager, or take the role away, and write it to the history.

    The role is the permission manager_access, given to the user himself. An admin
    cannot be changed here, and a role that comes from a group or from a state has
    to be taken away there.

    :param actor: The admin who makes the change
    :param user: The builder
    :param manager: True to make a manager, False to take the role away
    :raises django.core.exceptions.ValidationError: When the user is an admin, or
        the role comes from a group or a state
    :return: True if the role changed
    """

    user = User.objects.get(pk=user.pk)  # fresh: the permissions may have changed
    role = role_of(user)

    if role == ROLE_ADMIN:
        raise ValidationError(
            _("The role of an admin is set in the admin site of Auth.")
        )

    direct, via = manager_sources(user)
    permission = Permission.objects.get(
        content_type__app_label="evebuilders", codename=MANAGER_CODENAME
    )

    if manager:
        if role == ROLE_MANAGER:
            return False
        user.user_permissions.add(permission)
        before, after = "Builder", "Manager"
    else:
        if via:
            raise ValidationError(
                _(
                    "The manager role of %(name)s comes from %(source)s: "
                    "take it away there."
                )
                % {"name": display_name(user), "source": via}
            )
        if not direct:
            return False
        user.user_permissions.remove(permission)
        before, after = "Manager", "Builder"

    OrderEvent.objects.create(
        kind=OrderEvent.Kind.ROLE_CHANGED,
        actor=actor,
        description=f"Role of {display_name(user)}: {before} -> {after}",
    )

    return True
