"""Item search tests"""

# Standard Library
from unittest.mock import patch

# Third Party
# EVE Universe
from eveuniverse.models import EveCategory, EveGroup, EveType

# Django
from django.test import TestCase
from django.urls import reverse

# AA EVE Builders
from evebuilders import app_settings
from evebuilders.catalog import search_items
from evebuilders.tests.test_views import make_user


def make_type(type_id: int, name: str, group: EveGroup, published: bool = True):
    """Create an EVE type"""

    return EveType.objects.create(
        id=type_id, name=name, eve_group=group, published=published
    )


class SearchTestCase(TestCase):
    """A configured category (6, ships) and an unconfigured one (99)"""

    @classmethod
    def setUpTestData(cls) -> None:
        ship_category = EveCategory.objects.create(id=6, name="Ship", published=True)
        cls.frigate_group = EveGroup.objects.create(
            id=25, name="Frigate", eve_category=ship_category, published=True
        )
        other_category = EveCategory.objects.create(id=99, name="Other", published=True)
        cls.other_group = EveGroup.objects.create(
            id=999, name="Other group", eve_category=other_category, published=True
        )


class TestSearchItems(SearchTestCase):
    """search_items"""

    def test_finds_by_part_of_the_name(self):
        make_type(597, "Punisher", self.frigate_group)

        self.assertEqual(
            search_items("nish"),
            [{"id": 597, "name": "Punisher", "group": "Frigate", "category": "Ship"}],
        )

    def test_is_case_insensitive(self):
        make_type(597, "Punisher", self.frigate_group)

        self.assertEqual([r["id"] for r in search_items("PUNI")], [597])

    def test_too_short_query_finds_nothing(self):
        make_type(597, "Punisher", self.frigate_group)

        for query in ("", " ", "p", " p "):
            with self.subTest(query=query):
                self.assertEqual(search_items(query), [])

    def test_names_starting_with_the_query_come_first(self):
        make_type(1, "Arch Rifter", self.frigate_group)
        make_type(2, "Rifter", self.frigate_group)

        names = [r["name"] for r in search_items("rifter")]

        self.assertEqual(names, ["Rifter", "Arch Rifter"])

    def test_only_configured_categories_are_searched(self):
        make_type(597, "Punisher", self.frigate_group)
        make_type(1, "Punisher Other", self.other_group)

        self.assertEqual([r["id"] for r in search_items("punisher")], [597])

    def test_configured_groups_are_searched_too(self):
        make_type(1, "Punisher Other", self.other_group)

        with patch.object(app_settings, "EVEBUILDERS_CATALOG_GROUP_IDS", [999]):
            result = search_items("punisher")

        self.assertEqual([r["id"] for r in result], [1])

    def test_unpublished_types_are_skipped(self):
        make_type(597, "Punisher", self.frigate_group, published=False)

        self.assertEqual(search_items("punisher"), [])

    def test_result_count_is_limited(self):
        for i in range(25):
            make_type(1000 + i, f"Test Ship {i:02d}", self.frigate_group)

        self.assertEqual(len(search_items("test ship")), 20)
        self.assertEqual(len(search_items("test ship", limit=5)), 5)


class TestItemSearchView(SearchTestCase):
    """The JSON endpoint"""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.manager = make_user("manager", "manage_access")
        cls.builder = make_user("builder", "builder_access")
        make_type(597, "Punisher", cls.frigate_group)

    def test_anonymous_and_builders_are_sent_away(self):
        url = reverse("evebuilders:item_search")

        self.assertEqual(self.client.get(url, {"q": "puni"}).status_code, 302)

        self.client.force_login(self.builder)
        self.assertEqual(self.client.get(url, {"q": "puni"}).status_code, 302)

    def test_manager_gets_json(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:item_search"), {"q": "puni"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "results": [
                    {
                        "id": 597,
                        "name": "Punisher",
                        "group": "Frigate",
                        "category": "Ship",
                    }
                ]
            },
        )

    def test_missing_query_gives_no_results(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:item_search"))

        self.assertEqual(response.json(), {"results": []})

    def test_post_is_not_allowed(self):
        self.client.force_login(self.manager)

        response = self.client.post(reverse("evebuilders:item_search"))

        self.assertEqual(response.status_code, 405)
