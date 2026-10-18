"""Permission helpers"""

BUILDER_ACCESS = "evebuilders.builder_access"
MANAGE_ACCESS = "evebuilders.manage_access"


def has_any_access(user) -> bool:
    """Return True if the user may see the plugin at all"""

    return user.has_perm(BUILDER_ACCESS) or user.has_perm(MANAGE_ACCESS)