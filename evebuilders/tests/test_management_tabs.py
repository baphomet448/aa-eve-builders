"""The three tabs of the management"""

# Django
from django.test import override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES

TABS = {
    "contracts": "evebuilders:management",
    "statistics": "evebuilders:management_statistics",
    "history": "evebuilders:management_history",
}


@override_settings(STORAGES=TEST_STORAGES)
class TestManagementTabs(ViewsTestCase):
    """Access, the tab strip and what each tab shows"""

    def _get(self, user, name):
        self.client.force_login(user)

        return self.client.get(reverse(name))

    def test_only_managers_get_in(self):
        for name in TABS.values():
            with self.subTest(page=name):
                self.client.logout()
                self.assertEqual(self.client.get(reverse(name)).status_code, 302)

                self.client.force_login(self.builder)
                self.assertEqual(self.client.get(reverse(name)).status_code, 302)

                self.assertEqual(self._get(self.manager, name).status_code, 200)

    def test_every_tab_has_the_strip_and_marks_itself(self):
        for tab, name in TABS.items():
            response = self._get(self.manager, name)
            with self.subTest(tab=tab):
                for other in TABS:
                    self.assertContains(response, f'data-tab="{other}"')
                self.assertContains(
                    response, f'class="nav-link active" data-tab="{tab}"'
                )

    def test_management_stays_marked_in_the_top_bar(self):
        for name in TABS.values():
            response = self._get(self.manager, name)
            with self.subTest(page=name):
                # The top bar plus the tab: two active links
                self.assertContains(response, "nav-link active", count=2)

    def test_the_contracts_tab_shows_the_two_lists_only(self):
        response = self._get(self.manager, TABS["contracts"])

        self.assertContains(response, "Contracts that need attention")
        self.assertContains(response, "Contracts waiting for acceptance")
        self.assertNotContains(response, "Latest activity")

    def test_the_history_tab_shows_the_latest_activity(self):
        response = self._get(self.manager, TABS["history"])

        self.assertContains(response, "Latest activity")
        self.assertNotContains(response, "Contracts that need attention")

    def test_the_statistics_tab_shows_the_statistics(self):
        response = self._get(self.manager, TABS["statistics"])

        self.assertContains(response, "General statistics")
        self.assertContains(response, "Current statistics")
