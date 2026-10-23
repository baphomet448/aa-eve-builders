"""App Settings"""

# Django
from django.conf import settings

# EVE categories kept loaded in the item catalog:
# 4 Material, 6 Ship, 7 Module, 8 Charge, 18 Drone, 22 Deployable,
# 32 Subsystem, 65 Structure, 66 Structure Module, 87 Fighter.
# Override in local.py, e.g. EVEBUILDERS_CATALOG_CATEGORY_IDS = [6, 18]
EVEBUILDERS_CATALOG_CATEGORY_IDS = list(
    getattr(
        settings,
        "EVEBUILDERS_CATALOG_CATEGORY_IDS",
        [4, 6, 7, 8, 18, 22, 32, 65, 66, 87],
    )
)

# Extra single groups loaded on top of the categories above, for cases where
# a whole category is too big (e.g. 1136 = Fuel Block).
EVEBUILDERS_CATALOG_GROUP_IDS = list(
    getattr(settings, "EVEBUILDERS_CATALOG_GROUP_IDS", [])
)

# A new catalog sync request is ignored if one was started less than this many
# minutes ago (eveuniverse silently drops duplicate tasks, so we guard ourselves).
EVEBUILDERS_CATALOG_MIN_INTERVAL_MINUTES = int(
    getattr(settings, "EVEBUILDERS_CATALOG_MIN_INTERVAL_MINUTES", 15)
)