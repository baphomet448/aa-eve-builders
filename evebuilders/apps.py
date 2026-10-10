"""App Configuration"""

# Django
from django.apps import AppConfig

# AA EVE Builders
from evebuilders import __version__


class EveBuildersConfig(AppConfig):
    """App Config"""

    name = "evebuilders"
    label = "evebuilders"
    verbose_name = f"EVE Builders v{__version__}"
