"""Hook into Alliance Auth"""

# Django
from django.utils.translation import gettext_lazy as _

# Alliance Auth
from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook

# AA EVE Builders
from evebuilders import urls
from evebuilders.permissions import has_any_access


class CorporateOrdersMenuItem(MenuItemHook):
    """Sidebar entry for the corporate orders. Only builders and managers see it."""

    def __init__(self):
        MenuItemHook.__init__(
            self,
            _("Corporate orders"),
            "fas fa-clipboard-list fa-fw",
            "evebuilders:orders",
            navactive=["evebuilders:orders", "evebuilders:new_order"],
        )

    def render(self, request):
        """Render the menu item"""

        if has_any_access(request.user):
            return MenuItemHook.render(self, request)

        return ""


class MyOrdersMenuItem(MenuItemHook):
    """Sidebar entry for the orders the user has taken."""

    def __init__(self):
        MenuItemHook.__init__(
            self,
            _("My orders"),
            "fas fa-user-check fa-fw",
            "evebuilders:my_orders",
            navactive=["evebuilders:my_orders"],
        )

    def render(self, request):
        """Render the menu item"""

        if has_any_access(request.user):
            return MenuItemHook.render(self, request)

        return ""


@hooks.register("menu_item_hook")
def register_corporate_orders_menu():
    """Register the sidebar entry for the corporate orders"""

    return CorporateOrdersMenuItem()


@hooks.register("menu_item_hook")
def register_my_orders_menu():
    """Register the sidebar entry for the user's own orders"""

    return MyOrdersMenuItem()


@hooks.register("url_hook")
def register_urls():
    """Register app urls"""

    return UrlHook(urls, "evebuilders", r"^evebuilders/")
