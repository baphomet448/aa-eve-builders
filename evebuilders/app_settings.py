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

# Minimum number of seconds between two contract syncs (the button and the
# schedule alike). ESI keeps its answers for a few minutes anyway.
EVEBUILDERS_SYNC_MIN_INTERVAL_SECONDS = int(
    getattr(settings, "EVEBUILDERS_SYNC_MIN_INTERVAL_SECONDS", 60)
)

# Discord webhooks. An empty URL means: no notifications to that channel.
# "New order" channel: new, changed and removed orders.
EVEBUILDERS_DISCORD_NEW_ORDER_WEBHOOK_URL = str(
    getattr(settings, "EVEBUILDERS_DISCORD_NEW_ORDER_WEBHOOK_URL", "")
).strip()
EVEBUILDERS_DISCORD_NEW_ORDER_THREAD_ID = str(
    getattr(settings, "EVEBUILDERS_DISCORD_NEW_ORDER_THREAD_ID", "")
).strip()

# "Complete" channel: reports about contracts, deliveries, giving back, problems.
EVEBUILDERS_DISCORD_COMPLETE_WEBHOOK_URL = str(
    getattr(settings, "EVEBUILDERS_DISCORD_COMPLETE_WEBHOOK_URL", "")
).strip()
EVEBUILDERS_DISCORD_COMPLETE_THREAD_ID = str(
    getattr(settings, "EVEBUILDERS_DISCORD_COMPLETE_THREAD_ID", "")
).strip()

# Announce in Discord that a builder took (a part of) an order. The live system
# does not send this, the officers asked for it.
EVEBUILDERS_DISCORD_NOTIFY_TAKEN = bool(
    getattr(settings, "EVEBUILDERS_DISCORD_NOTIFY_TAKEN", True)
)