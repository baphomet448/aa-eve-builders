"""Catalog sync tests"""

from datetime import timedelta
from unittest.mock import patch

# Django
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

# EVE Universe
from eveuniverse.models import EveCategory, EveGroup, EveType

# AA EVE Builders
from evebuilders import app_settings
from evebuilders.catalog import SyncResult, catalog_overview, start_catalog_sync
from evebuilders.models import CatalogSync

User = get_user_model()

MODULE = "evebuilders.catalog"


class TestStartCatalogSync(TestCase):
    """start_catalog_sync with ESI and the eveuniverse task mocked out"""

    def setUp(self):
        esi_patcher = patch(f"{MODULE}.is_esi_online", return_value=True)
        load_patcher = patch(f"{MODULE}.load_eve_types")
        self.mock_esi = esi_patcher.start()
        self.mock_load = load_patcher.start()
        self.addCleanup(esi_patcher.stop)
        self.addCleanup(load_patcher.stop)
        self.user = User.objects.create_user("catalog_manager")

    def test_starts_and_records_state(self):
        result = start_catalog_sync(user=self.user)

        self.assertEqual(result, SyncResult.STARTED)
        self.mock_load.delay.assert_called_once_with(
            category_ids=[4, 6, 7, 8, 18, 22, 32, 65, 66, 87], group_ids=None
        )
        state = CatalogSync.get_solo()
        self.assertIsNotNone(state.started_at)
        self.assertEqual(state.started_by, self.user)
        self.assertEqual(state.category_ids, "4,6,7,8,18,22,32,65,66,87")
        self.assertEqual(state.group_ids, "")
        self.assertEqual(state.last_error, "")

    def test_second_request_is_refused_while_recent(self):
        self.assertEqual(start_catalog_sync(), SyncResult.STARTED)
        self.assertEqual(start_catalog_sync(), SyncResult.TOO_SOON)

        self.assertEqual(self.mock_load.delay.call_count, 1)

    def test_allowed_again_after_the_interval(self):
        CatalogSync.get_solo()
        minutes = app_settings.EVEBUILDERS_CATALOG_MIN_INTERVAL_MINUTES + 1
        CatalogSync.objects.filter(pk=1).update(
            started_at=timezone.now() - timedelta(minutes=minutes)
        )

        self.assertEqual(start_catalog_sync(), SyncResult.STARTED)
        self.assertEqual(self.mock_load.delay.call_count, 1)

    def test_esi_offline(self):
        self.mock_esi.return_value = False

        self.assertEqual(start_catalog_sync(), SyncResult.ESI_OFFLINE)

        self.mock_load.delay.assert_not_called()
        state = CatalogSync.get_solo()
        self.assertIsNone(state.started_at)
        self.assertIn("offline", state.last_error)

    def test_nothing_to_load(self):
        with patch.object(app_settings, "EVEBUILDERS_CATALOG_CATEGORY_IDS", []):
            result = start_catalog_sync()

        self.assertEqual(result, SyncResult.NOTHING_TO_LOAD)
        self.mock_load.delay.assert_not_called()

    def test_groups_are_passed_on(self):
        with patch.object(app_settings, "EVEBUILDERS_CATALOG_GROUP_IDS", [1136]):
            result = start_catalog_sync()

        self.assertEqual(result, SyncResult.STARTED)
        _, kwargs = self.mock_load.delay.call_args
        self.assertEqual(kwargs["group_ids"], [1136])
        self.assertEqual(CatalogSync.get_solo().group_ids, "1136")

    def test_failed_start_gives_the_slot_back(self):
        self.mock_load.delay.side_effect = RuntimeError("broker down")

        self.assertEqual(start_catalog_sync(), SyncResult.FAILED)

        state = CatalogSync.get_solo()
        self.assertIsNone(state.started_at)
        self.assertIn("broker down", state.last_error)

        self.mock_load.delay.side_effect = None
        self.assertEqual(start_catalog_sync(), SyncResult.STARTED)

class TestCatalogOverview(TestCase):
    """Rows for the settings page"""

    def test_one_row_per_configured_category_with_counts(self):
        category = EveCategory.objects.create(id=6, name="Ship", published=True)
        group = EveGroup.objects.create(
            id=25, name="Frigate", eve_category=category, published=True
        )
        EveType.objects.create(id=597, name="Punisher", eve_group=group, published=True)
        EveType.objects.create(id=598, name="Breacher", eve_group=group, published=True)

        rows = {
            row["id"]: row for row in catalog_overview() if row["kind"] == "category"
        }

        self.assertEqual(sorted(rows), [4, 6, 7, 8, 18, 22, 32, 65, 66, 87])
        self.assertEqual(rows[6]["name"], "Ship")
        self.assertEqual(rows[6]["count"], 2)
        self.assertEqual(rows[4]["name"], "")
        self.assertEqual(rows[4]["count"], 0)

    def test_configured_groups_are_listed(self):
        category = EveCategory.objects.create(id=4, name="Material", published=True)
        group = EveGroup.objects.create(
            id=1136, name="Fuel Block", eve_category=category, published=True
        )
        EveType.objects.create(
            id=4051, name="Nitrogen Fuel Block", eve_group=group, published=True
        )

        with patch.object(app_settings, "EVEBUILDERS_CATALOG_GROUP_IDS", [1136]):
            rows = [row for row in catalog_overview() if row["kind"] == "group"]

        self.assertEqual(
            rows, [{"kind": "group", "id": 1136, "name": "Fuel Block", "count": 1}]
        )