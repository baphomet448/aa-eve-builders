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
    path("orders/<int:order_id>/take/", views.take_order_view, name="take_order"),
    path("orders/<int:order_id>/discard/", views.discard_view, name="discard"),
    path("my-orders/", views.my_orders, name="my_orders"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/esi/connect/", views.connect_esi, name="connect_esi"),
    path("settings/sync-catalog/", views.start_sync, name="sync_catalog"),
    path("items/search/", views.item_search, name="item_search"),
]