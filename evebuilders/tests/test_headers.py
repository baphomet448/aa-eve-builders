"""Column titles and the alignment of the order tables"""

# Django
from django.test import override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES


@override_settings(STORAGES=TEST_STORAGES)
class TestOrderTables(ViewsTestCase):
    """The titles, the centred columns and the hint on the status"""

    def _page(self, user, name):
        self.client.force_login(user)

        return self.client.get(reverse(f"evebuilders:{name}"))

    @staticmethod
    def _head(response):
        return response.content.decode().split("<thead>")[1].split("</thead>")[0]

    def test_the_order_list_titles(self):
        head = self._head(self._page(self.manager, "orders"))

        for title in ("Available", "On review", "Access"):
            with self.subTest(title=title):
                self.assertIn(title, head)
        self.assertNotIn("Access level", head)

    def test_the_order_list_centres_status_priority_and_access(self):
        response = self._page(self.manager, "orders")

        # The cells of a row, and the three titles above them
        self.assertContains(response, '<td class="text-center" data-value="')
        self.assertContains(response, 'class="text-center" data-sort="number"', count=3)

    def test_my_orders_titles_and_instruction(self):
        self._take(self.builder, 5)

        response = self._page(self.builder, "my_orders")
        head = self._head(response)

        self.assertIn("Receiver", head)
        self.assertIn("On review", head)
        self.assertNotIn("In contracts", head)
        self.assertContains(response, "Watch the status")
        self.assertContains(response, 'from the "Receiver" column')

    def test_my_orders_has_two_line_cells_for_status_and_dates(self):
        self._take(self.builder, 5)

        response = self._page(self.builder, "my_orders")
        head = self._head(response)

        # Status above priority, the due date above the date to give back until:
        # each line is its own title that sorts by its own value
        self.assertIn("Priority", head)
        self.assertIn("Give back until", head)
        self.assertEqual(head.count('data-sort-field="value2"'), 2)
        self.assertContains(response, 'data-value2="', count=2)

    def test_the_sorting_has_three_states(self):
        response = self._page(self.manager, "orders")

        # The third click brings back the order from the server
        self.assertContains(response, "positions.get(a) - positions.get(b)")
