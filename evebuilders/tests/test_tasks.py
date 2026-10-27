"""Task and management command tests"""

# Standard Library
from io import StringIO
from unittest.mock import patch

# Django
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

# AA EVE Builders
from evebuilders.catalog import SyncResult
from evebuilders.tasks import sync_catalog

COMMAND_MODULE = "evebuilders.management.commands.evebuilders_sync_catalog"


class TestSyncCatalogTask(TestCase):
    """The scheduled task only delegates to start_catalog_sync"""

    @patch("evebuilders.tasks.start_catalog_sync", return_value=SyncResult.STARTED)
    def test_returns_the_result_value(self, mock_start):
        self.assertEqual(sync_catalog(), "started")
        mock_start.assert_called_once_with()


class TestSyncCatalogCommand(TestCase):
    """evebuilders_sync_catalog"""

    @patch(f"{COMMAND_MODULE}.start_catalog_sync")
    def test_started(self, mock_start):
        mock_start.return_value = SyncResult.STARTED
        out = StringIO()

        call_command("evebuilders_sync_catalog", stdout=out)

        self.assertIn("started", out.getvalue())

    @patch(f"{COMMAND_MODULE}.start_catalog_sync")
    def test_too_soon_is_not_an_error(self, mock_start):
        mock_start.return_value = SyncResult.TOO_SOON
        out = StringIO()

        call_command("evebuilders_sync_catalog", stdout=out)

        self.assertIn("recently", out.getvalue())

    @patch(f"{COMMAND_MODULE}.start_catalog_sync")
    def test_offline_and_failure_are_errors(self, mock_start):
        for result in (SyncResult.ESI_OFFLINE, SyncResult.FAILED):
            with self.subTest(result=result):
                mock_start.return_value = result
                with self.assertRaises(CommandError):
                    call_command("evebuilders_sync_catalog", stdout=StringIO())