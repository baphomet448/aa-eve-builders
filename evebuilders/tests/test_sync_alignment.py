"""Syncing right after ESI refreshed its data"""

# Standard Library
from datetime import timedelta
from unittest.mock import patch

# Django
from django.test import TestCase
from django.utils import timezone

# AA EVE Builders
from evebuilders.models import ContractSource
from evebuilders.sync import (
    CACHE_MARGIN,
    RETRY_AFTER_FAILURE,
    SyncAttempt,
    SyncReport,
    next_sync_time,
)
from evebuilders.tasks import sync_contracts

TASKS = "evebuilders.tasks"


def make_source(**fields) -> ContractSource:
    return ContractSource.objects.create(
        corporation_id=98000001, corporation_name="Test Corp", **fields
    )


class TestNextSyncTime(TestCase):
    """next_sync_time"""

    def test_right_after_the_esi_answer_expires(self):
        now = timezone.now()
        expires = now + timedelta(minutes=3)
        source = make_source(
            esi_expires_at=expires, last_sync_at=now, last_success_at=now
        )

        self.assertEqual(next_sync_time(source), expires + CACHE_MARGIN)

    def test_without_an_expiry_it_is_now(self):
        source = make_source()
        before = timezone.now()

        result = next_sync_time(source)

        self.assertGreaterEqual(result, before)
        self.assertLessEqual(result, timezone.now())

    def test_after_a_failure_it_waits_a_while(self):
        failed_at = timezone.now()
        source = make_source(
            last_sync_at=failed_at,
            last_success_at=failed_at - timedelta(hours=1),
            esi_expires_at=failed_at - timedelta(minutes=30),
            last_error="refused",
        )

        self.assertEqual(next_sync_time(source), failed_at + RETRY_AFTER_FAILURE)

    def test_a_failure_before_any_success(self):
        failed_at = timezone.now()
        source = make_source(last_sync_at=failed_at, last_error="refused")

        self.assertEqual(next_sync_time(source), failed_at + RETRY_AFTER_FAILURE)


class TestScheduledSyncTiming(TestCase):
    """The scheduled task syncs only when it makes sense"""

    def test_it_waits_while_esi_still_serves_the_old_answer(self):
        now = timezone.now()
        make_source(
            esi_expires_at=now + timedelta(minutes=3),
            last_sync_at=now,
            last_success_at=now,
        )

        with patch(f"{TASKS}.sync_now") as mock_sync:
            result = sync_contracts()

        self.assertEqual(result, "not_yet")
        mock_sync.assert_not_called()

    def test_it_syncs_once_the_answer_has_expired(self):
        earlier = timezone.now() - timedelta(minutes=6)
        make_source(
            esi_expires_at=timezone.now() - timedelta(minutes=1),
            last_sync_at=earlier,
            last_success_at=earlier,
        )

        with patch(f"{TASKS}.sync_now") as mock_sync:
            mock_sync.return_value = SyncAttempt(report=SyncReport(seen=1))
            result = sync_contracts()

        self.assertEqual(result, "ok")
        mock_sync.assert_called_once()

    def test_it_does_not_ask_again_right_after_a_failure(self):
        make_source(
            last_sync_at=timezone.now() - timedelta(minutes=1),
            last_success_at=timezone.now() - timedelta(hours=1),
            last_error="refused",
        )

        with patch(f"{TASKS}.sync_now") as mock_sync:
            result = sync_contracts()

        self.assertEqual(result, "not_yet")
        mock_sync.assert_not_called()

    def test_it_tries_again_a_while_after_a_failure(self):
        make_source(
            last_sync_at=timezone.now() - timedelta(minutes=6),
            last_success_at=timezone.now() - timedelta(hours=1),
            last_error="refused",
        )

        with patch(f"{TASKS}.sync_now") as mock_sync:
            mock_sync.return_value = SyncAttempt(report=SyncReport(seen=1))
            result = sync_contracts()

        self.assertEqual(result, "ok")
        mock_sync.assert_called_once()