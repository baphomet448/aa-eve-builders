"""The look of the tables: the stripes, the dashes between the columns, My orders"""

# Django
from django.test import override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES

MARKER = "Vertical separators between the columns"
DASH = ".table > :not(caption) > * > * + *::before"
OLD_BORDER = ".table > :not(caption) > * > * + * {"
STRIPE = ".table > tbody > tr:nth-of-type(odd) > *"

PAGES = (
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


@override_settings(STORAGES=TEST_STORAGES)
class TestTableStyle(ViewsTestCase):
    """self.manager is an admin: every page is open to him"""

    def ts_get(self, name: str):
        self.client.force_login(self.manager)

        return self.client.get(reverse(name))

    def ts_css(self, name: str = "evebuilders:orders") -> str:
        return self.ts_get(name).content.decode()

    def test_every_page_with_a_table_has_the_dashes_and_the_stripes(self):
        for name in PAGES:
            with self.subTest(page=name):
                response = self.ts_get(name)

                self.assertContains(response, MARKER)
                self.assertContains(response, DASH)
                self.assertContains(response, STRIPE)

    def test_a_dash_is_short_and_does_not_reach_the_edges_of_the_row(self):
        content = self.ts_css()
        rule = content[content.index(DASH) :][:400]

        self.assertIn("position: absolute", rule)
        self.assertIn("top: 0.35rem", rule)
        self.assertIn("bottom: 0.35rem", rule)
        self.assertIn("border-left: 1px solid", rule)

    def test_the_old_continuous_border_is_gone(self):
        for name in PAGES:
            with self.subTest(page=name):
                self.assertNotContains(self.ts_get(name), OLD_BORDER)

    def test_the_stripes_have_the_colour_of_the_order_card(self):
        content = self.ts_css()
        rule = content[content.index(STRIPE) :][:200]

        self.assertIn("rgba(128, 128, 128, 0.08)", rule)

    def test_the_statistics_tables_have_no_stripes_of_their_own(self):
        response = self.ts_get("evebuilders:management_statistics")

        self.assertNotContains(response, "table-striped")

    def test_the_table_of_my_orders_does_not_get_narrower_than_its_content(self):
        response = self.ts_get("evebuilders:my_orders")

        self.assertContains(
            response, "#evebuilders-my-orders { width: max-content; min-width: 100%; }"
        )

    def test_the_corporate_orders_are_left_as_they_were(self):
        response = self.ts_get("evebuilders:orders")

        self.assertNotContains(response, "max-content")
