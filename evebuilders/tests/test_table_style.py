"""The look of the tables: the stripes, the lines between the columns, the alignment"""

# Standard Library
import re

# Django
from django.test import override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.messages import display_name
from evebuilders.models import Order
from evebuilders.tests.test_contracts_review import ReviewTestCase
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES

LINE = ".table > :not(caption) > * > * + * {"
STRIPE = ".table > tbody > tr:nth-of-type(odd) > *"
NO_HOVER = ".table.table-hover > tbody > tr:hover > *"

PAGES = (
    "evebuilders:orders",
    "evebuilders:my_orders",
    "evebuilders:management",
    "evebuilders:management_statistics",
    "evebuilders:management_history",
    "evebuilders:contracts_review",
    "evebuilders:builder_levels",
    "evebuilders:stations",
    "evebuilders:settings",
    "evebuilders:discord_settings",
)


def header_attributes(html: str, title: str) -> list[str]:
    """The attributes of every table header that has this title"""

    return re.findall(rf"<th([^>]*)>(?:<a [^>]*>)?{re.escape(title)}", html)


@override_settings(STORAGES=TEST_STORAGES)
class TestTableStyle(ViewsTestCase):
    """self.manager is an admin: every page is open to him"""

    def ts_get(self, name: str):
        self.client.force_login(self.manager)

        return self.client.get(reverse(name))

    def ts_html(self, name: str = "evebuilders:orders") -> str:
        return self.ts_get(name).content.decode()

    def test_every_page_has_the_stripes_the_lines_and_no_hover(self):
        for name in PAGES:
            with self.subTest(page=name):
                response = self.ts_get(name)

                self.assertContains(response, STRIPE)
                self.assertContains(response, LINE)
                self.assertContains(response, NO_HOVER)

    def test_a_line_is_a_border_the_height_of_the_cell(self):
        html = self.ts_html()
        rule = html[html.index(LINE) :][:200]

        self.assertIn("border-left: 1px solid", rule)
        self.assertNotIn(
            "::before", html[html.index(LINE) - 100 : html.index(LINE) + 400]
        )

    def test_the_dashes_are_gone(self):
        for name in PAGES:
            with self.subTest(page=name):
                html = self.ts_html(name)

                self.assertNotIn("* + *::before", html)
                self.assertNotIn("position: absolute; left: 0", html)

    def test_the_stripes_have_the_colour_of_the_order_card(self):
        html = self.ts_html()
        rule = html[html.index(STRIPE) :][:200]

        self.assertIn("rgba(128, 128, 128, 0.08)", rule)

    def test_the_hover_changes_nothing(self):
        html = self.ts_html()
        rule = html[html.index(NO_HOVER) :][:200]

        self.assertIn("--bs-table-bg-state: initial", rule)
        self.assertIn("--bs-table-color-state: initial", rule)

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


class TestRightAlignment(ReviewTestCase):
    """The columns "Destination" and "Builder" are aligned to the right"""

    def ta_get(self, name: str, *args) -> str:
        self.client.force_login(self.manager)

        return self.client.get(reverse(name, args=args)).content.decode()

    def ta_right(self, html: str, title: str) -> None:
        attributes = header_attributes(html, title)

        self.assertTrue(attributes, f"No header {title}")
        for one in attributes:
            self.assertIn("text-end", one, f"The header {title} is not on the right")

    def test_the_list_of_orders(self):
        Order.objects.filter(pk=self.order.pk).update(destination="Jita 4-4")

        html = self.ta_get("evebuilders:orders")

        self.ta_right(html, "Destination")
        self.assertIn('<td class="text-end">Jita 4-4', html)

    def test_the_page_of_the_contracts_on_review(self):
        Order.objects.filter(pk=self.order.pk).update(destination="Jita 4-4")
        self.cr_contract(5, "5000000")

        html = self.ta_get("evebuilders:contracts_review")

        self.ta_right(html, "Destination")
        self.ta_right(html, "Builder")
        self.assertIn('<td class="text-end">Jita 4-4</td>', html)
        self.assertIn(f'<td class="text-end">{display_name(self.other)}</td>', html)

    def test_the_contracts_waiting_on_the_management_page(self):
        self.cr_contract(5, "5000000")

        html = self.ta_get("evebuilders:management")

        self.ta_right(html, "Builder")
        self.assertIn(f'<td class="text-end">{display_name(self.other)}</td>', html)

    def test_the_tables_of_an_order(self):
        self.cr_contract(5, "5000000")

        html = self.ta_get("evebuilders:order_detail", self.order.pk)

        self.ta_right(html, "Builder")
        self.assertEqual(len(header_attributes(html, "Builder")), 2)
        name = display_name(self.other)
        self.assertEqual(html.count(f'<td class="text-end">{name}</td>'), 2)
