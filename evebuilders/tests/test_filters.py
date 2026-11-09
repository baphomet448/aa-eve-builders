"""Search and filters above the order list and the list of builders"""

# Django
from django.test import override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES


@override_settings(STORAGES=TEST_STORAGES)
class TestOrderListFilters(ViewsTestCase):
    """The panel and the data the filters work on"""

    def _page(self, user):
        self.client.force_login(user)

        return self.client.get(reverse("evebuilders:orders"))

    def test_the_panel_is_there(self):
        response = self._page(self.manager)

        self.assertContains(response, 'data-filter-for="evebuilders-orders"')
        self.assertContains(response, "data-filter-text")
        self.assertContains(response, 'data-filter-eq="status"')
        self.assertContains(response, 'data-filter-eq="priority"')
        self.assertContains(response, 'data-filter-positive="free"')
        self.assertContains(response, "data-filter-reset")

    def test_only_managers_can_filter_by_level(self):
        manager = self._page(self.manager)
        builder = self._page(self.builder)

        self.assertContains(manager, 'data-filter-eq="level"')
        self.assertNotContains(builder, 'data-filter-eq="level"')

    def test_a_row_carries_what_the_filters_compare(self):
        response = self._page(self.manager)

        self.assertContains(response, 'data-status="NEW"')
        self.assertContains(response, 'data-priority="MEDIUM"')
        self.assertContains(response, 'data-level="1"')
        self.assertContains(response, 'data-free="1000"')
        self.assertContains(response, f'data-search="{self.order.number} Punisher')

    def test_the_script_is_on_the_page(self):
        response = self._page(self.manager)

        self.assertContains(response, "[data-filter-for]")


@override_settings(STORAGES=TEST_STORAGES)
class TestBuilderLevelsFilters(ViewsTestCase):
    """The same for the list of builders"""

    def _page(self):
        self.client.force_login(self.manager)

        return self.client.get(reverse("evebuilders:builder_levels"))

    def test_the_panel_the_sorting_and_the_data(self):
        response = self._page()

        self.assertContains(response, 'data-filter-for="evebuilders-builders"')
        self.assertContains(response, 'id="evebuilders-builders"')
        self.assertContains(response, 'data-sort="text"')
        self.assertContains(response, 'data-sort="number"')
        self.assertContains(response, 'data-level="1"')

    def test_every_column_has_a_header(self):
        content = self._page().content.decode()

        head = content.split("<thead>")[1].split("</thead>")[0]
        row = content.split("<tbody>")[1].split("</tr>")[0]
        self.assertEqual(head.count("<th"), row.count("<td"))