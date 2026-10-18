"""Hook into Alliance Auth"""

# Django
from django.utils.translation import gettext_lazy as _

# Alliance Auth
from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook

# AA EVE Builders
from evebuilders import urls
from evebuilders.permissions import has_any_access


class EveBuildersMenuItem(MenuItemHook):
    """This class ensures only authorized users will see the menu entry"""

    def __init__(self):
        # setup menu entry for sidebar
        MenuItemHook.__init__(
            self,
            _("EVE Builders"),
            "fas fa-cube fa-fw",
            "evebuilders:index",
            navactive=["evebuilders:"],
        )

    def render(self, request):
        """Render the menu item"""

        if has_any_access(request.user):
            return MenuItemHook.render(self, request)

        return ""


@hooks.register("menu_item_hook")
def register_menu():
    """Register the menu item"""

    return EveBuildersMenuItem()


@hooks.register("url_hook")
def register_urls():
    """Register app urls"""

    return UrlHook(urls, "evebuilders", r"^evebuilders/")
