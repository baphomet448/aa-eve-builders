"""The scheduled contract sync and its status on the settings page"""

# Standard Library
from datetime import timedelta
from unittest.mock import patch

# Django
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

# AA EVE Builders
from evebuilders.models import ContractSource
from evebuilders.sync import SyncAttempt, SyncReport
from evebuilders.tasks import sync_contracts
from evebuilders.tests.test_views import TEST_STORAGES, make_user

TASKS = "evebuilders.tasks"


class TestSyncContractsTask(TestCase):
    """evebuilders.tasks.sync_contracts"""

    def setUp(self):
        ContractSource.objects.create(
            corporation_id=98000001, corporation_name="Test Corp"
        )

    @patch(f"{TASKS}.sync_now")
    def test_ok(self, mock_sync):
        mock_sync.return_value = SyncAttempt(report=SyncReport(seen=5, credited=1))

        self.assertEqual(sync_contracts(), "ok")
        mock_sync.assert_called_once()

    @patch(f"{TASKS}.sync_now")
    def test_too_soon(self, mock_sync):
        mock_sync.return_value = SyncAttempt(too_soon=True, wait_seconds=10)

        self.assertEqual(sync_contracts(), "too_soon")

    @patch(f"{TASKS}.sync_now")
    def test_error(self, mock_sync):
        mock_sync.return_value = SyncAttempt(report=SyncReport(error="refused"))

        self.assertEqual(sync_contracts(), "error")

    @patch(f"{TASKS}.sync_now")
    def test_no_source_does_not_even_try(self, mock_sync):
        ContractSource.objects.all().delete()

        self.assertEqual(sync_contracts(), "no_source")
        mock_sync.assert_not_called()


@override_settings(STORAGES=TEST_STORAGES)
class TestSettingsStatus(TestCase):
    """The sync status in the ESI connection block"""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.manager = make_user("manager", "manage_access")

    def test_shows_when_contracts_were_checked(self):
        ContractSource.objects.create(
            corporation_id=98000001,
            corporation_name="Test Corp",
            connected_by=self.manager,
            connected_at=timezone.now(),
            last_sync_at=timezone.now() - timedelta(minutes=2),
            last_success_at=timezone.now() - timedelta(minutes=2),
            esi_expires_at=timezone.now() + timedelta(minutes=3),
        )
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:settings"))

        self.assertContains(response, "Last check")
        self.assertContains(response, "Last successful check")
        self.assertContains(response, "ESI answer valid until")

    def test_shows_the_last_problem(self):
        ContractSource.objects.create(
            corporation_id=98000001,
            corporation_name="Test Corp",
            connected_by=self.manager,
            connected_at=timezone.now(),
            token_ok=False,
            last_error="ESI refused the token (HTTP 403)",
        )
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:settings"))

        self.assertContains(response, "ESI refused the token (HTTP 403)")
