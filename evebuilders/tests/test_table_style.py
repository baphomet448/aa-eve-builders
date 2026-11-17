"""The look of the tables: the vertical separators and the table of My orders"""

# Django
from django.test import override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES

MARKER = "Vertical separators between the columns"
RULE = ".table > :not(caption) > * > * + *"


@override_settings(STORAGES=TEST_STORAGES)
class TestTableStyle(ViewsTestCase):
    """self.manager is an admin: every page is open to him"""

    def ts_get(self, name: str):
        self.client.force_login(self.manager)

        return self.client.get(reverse(name))

    def test_every_page_with_a_table_has_the_separators(self):
        pages = (
            "evebuilders:orders",
            "evebuilders:my_orders",
            "evebuilders:management",
            "evebuilders:management_statistics",
            "evebuilders:management_history",
            "evebuilders:builder_levels",
            "evebuilders:stations",
            "evebuilders:settings",
            "evebuilders:discord_settings",
        )

        for name in pages:
            with self.subTest(page=name):
                response = self.ts_get(name)

                self.assertContains(response, MARKER)
                self.assertContains(response, RULE)

    def test_the_separator_is_a_border_on_the_left_of_a_cell(self):
        content = self.ts_get("evebuilders:orders").content.decode()
        start = content.index(RULE)

        self.assertIn("border-left: 1px solid", content[start : start + 200])

    def test_the_table_of_my_orders_does_not_get_narrower_than_its_content(self):
        response = self.ts_get("evebuilders:my_orders")

        self.assertContains(
            response, "#evebuilders-my-orders { width: max-content; min-width: 100%; }"
        )

    def test_the_corporate_orders_are_left_as_they_were(self):
        response = self.ts_get("evebuilders:orders")

        self.assertNotContains(response, "max-content")
