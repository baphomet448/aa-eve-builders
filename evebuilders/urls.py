"""App URLs"""

# Django
from django.urls import path

# AA EVE Builders
from evebuilders import views

app_name: str = "evebuilders"  # pylint: disable=invalid-name

urlpatterns = [
    path("", views.index, name="index"),
]
