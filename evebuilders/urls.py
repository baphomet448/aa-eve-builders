"""App URLs"""

# Django
from django.urls import path

# AA EVE Builders
from evebuilders import views

app_name: str = "evebuilders"  # pylint: disable=invalid-name

urlpatterns = [
    path("", views.index, name="index"),
    path("orders/", views.order_list, name="orders"),
    path("orders/new/", views.new_order, name="new_order"),
    path("orders/<int:order_id>/", views.order_detail, name="order_detail"),
    path("orders/<int:order_id>/edit/", views.edit_order, name="edit_order"),
    path("orders/<int:order_id>/take/", views.take_order_view, name="take_order"),
    path("orders/<int:order_id>/discard/", views.discard_view, name="discard"),
    path("orders/<int:order_id>/release/", views.release_view, name="release"),
    path("orders/<int:order_id>/credit/", views.credit_view, name="credit"),
    path("my-orders/", views.my_orders, name="my_orders"),
    path("my-orders/sync/", views.sync_contracts_view, name="sync_contracts"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/builders/", views.builder_levels_view, name="builder_levels"),
    path(
        "settings/builders/<int:user_id>/level/",
        views.set_level_view,
        name="set_level",
    ),
    path("settings/esi/connect/", views.connect_esi, name="connect_esi"),
    path("settings/sync-catalog/", views.start_sync, name="sync_catalog"),
    path("items/search/", views.item_search, name="item_search"),
]