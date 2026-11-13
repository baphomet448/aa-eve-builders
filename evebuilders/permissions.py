"""Permission helpers: who may do what in the plugin

The plugin has three roles. Each is a permission of Alliance Auth that is given to
a user, to a group or to a state:

- admin (admin_access): everything, also the settings of ESI and Discord
- manager (manager_access): the orders, the builders and the management
- builder (builder_access): the orders that a builder may take

A higher role has the lower ones. Being a superuser of Django gives no role: the
permissions are looked at one by one, so a superuser has a role only when it is given
to him like to anybody else.
"""

# Django
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.models import Permission

BUILDER_CODENAME = "builder_access"
MANAGER_CODENAME = "manager_access"
ADMIN_CODENAME = "admin_access"
CODENAMES = (BUILDER_CODENAME, MANAGER_CODENAME, ADMIN_CODENAME)

# The same with the name of the app, as Django writes them
BUILDER_ACCESS = f"evebuilders.{BUILDER_CODENAME}"
MANAGER_ACCESS = f"evebuilders.{MANAGER_CODENAME}"
ADMIN_ACCESS = f"evebuilders.{ADMIN_CODENAME}"

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_BUILDER = "builder"
NO_ROLE = ""


def plugin_permissions(user) -> frozenset[str]:
    """
    The permissions of the plugin that a user has: given to him, to one of his
    groups or to his state. Being a superuser gives none of them.

    The answer is kept on the user object, so one request asks the database once.
    """

    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return frozenset()

    kept = getattr(user, "_evebuilders_permissions", None)
    if kept is not None:
        return kept

    of_the_plugin = {
        "content_type__app_label": "evebuilders",
        "codename__in": CODENAMES,
    }

    codenames = set(
        user.user_permissions.filter(**of_the_plugin).values_list("codename", flat=True)
    )
    codenames |= set(
        Permission.objects.filter(group__user=user, **of_the_plugin).values_list(
            "codename", flat=True
        )
    )

    state = getattr(getattr(user, "profile", None), "state", None)
    if state is not None:
        codenames |= set(
            state.permissions.filter(**of_the_plugin).values_list("codename", flat=True)
        )

    user._evebuilders_permissions = frozenset(codenames)

    return user._evebuilders_permissions


def role_of(user) -> str:
    """The highest role of a user: admin, manager, builder or none (empty)"""

    codenames = plugin_permissions(user)

    if ADMIN_CODENAME in codenames:
        return ROLE_ADMIN
    if MANAGER_CODENAME in codenames:
        return ROLE_MANAGER
    if BUILDER_CODENAME in codenames:
        return ROLE_BUILDER

    return NO_ROLE


def has_any_access(user) -> bool:
    """Return True if the user may see the plugin at all (any role)"""

    return role_of(user) != NO_ROLE


def is_manager(user) -> bool:
    """Return True for a manager and for an admin"""

    return role_of(user) in (ROLE_ADMIN, ROLE_MANAGER)


def is_admin(user) -> bool:
    """Return True for an admin"""

    return role_of(user) == ROLE_ADMIN


# Decorators for the views: a user without the role is sent to the login page
manager_required = user_passes_test(is_manager)
admin_required = user_passes_test(is_admin)
