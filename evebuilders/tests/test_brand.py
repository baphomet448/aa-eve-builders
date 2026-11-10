"""The name in the top bar of Auth"""

# Django
from django.test import override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES


@override_settings(STORAGES=TEST_STORAGES)
class TestBrand(ViewsTestCase):
    """The plugin calls itself PROB Builders in the top bar"""

    def test_the_top_bar_says_prob_builders(self):
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:orders"))

        self.assertContains(response, "PROB Builders")
