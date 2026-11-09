"""The Sync contracts button and sync_now"""

# Standard Library
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

# Django
from django.contrib.messages import constants, get_messages
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone as dj_timezone

# AA EVE Builders
from evebuilders.contracts import FetchResult
from evebuilders.models import ContractSource
from evebuilders.sync import SyncAttempt, SyncReport, sync_contracts, sync_now
from evebuilders.tests.test_views import TEST_STORAGES, make_user

SYNC = "evebuilders.sync"
VIEWS = "evebuilders.views"


class TestSyncNow(TestCase):
    """sync_now"""

    def setUp(self):
        self.source = ContractSource.objects.create(
            corporation_id=98000001, corporation_name="Test Corp"
        )

    @patch(f"{SYNC}.sync_contracts", return_value=SyncReport(seen=3))
    def test_runs_the_sync_and_claims_the_slot(self, mock_sync):
        attempt = sync_now()

        self.assertFalse(attempt.too_soon)
        self.assertEqual(attempt.report.seen, 3)
        mock_sync.assert_called_once()
        self.source.refresh_from_db()
        self.assertIsNotNone(self.source.last_sync_at)

    @patch(f"{SYNC}.sync_contracts", return_value=SyncReport())
    def test_a_second_request_right_away_is_too_soon(self, mock_sync):
        sync_now()

        attempt = sync_now()

        self.assertTrue(attempt.too_soon)
        self.assertGreater(attempt.wait_seconds, 0)
        self.assertLessEqual(attempt.wait_seconds, 60)
        self.assertIsNone(attempt.report)
        self.assertEqual(mock_sync.call_count, 1)

    @patch(f"{SYNC}.sync_contracts", return_value=SyncReport())
    def test_allowed_again_after_the_interval(self, mock_sync):
        ContractSource.objects.update(
            last_sync_at=dj_timezone.now() - timedelta(seconds=61)
        )

        attempt = sync_now()

        self.assertFalse(attempt.too_soon)
        self.assertEqual(mock_sync.call_count, 1)

    @patch(f"{SYNC}.sync_contracts", return_value=SyncReport())
    def test_the_interval_can_be_given(self, mock_sync):
        sync_now(min_interval=0)
        sync_now(min_interval=0)

        self.assertEqual(mock_sync.call_count, 2)

    @patch(f"{SYNC}.sync_contracts")
    def test_no_source(self, mock_sync):
        ContractSource.objects.all().delete()

        attempt = sync_now()

        self.assertTrue(attempt.report.error)
        mock_sync.assert_not_called()


class TestEsiExpires(TestCase):
    """The end of the ESI cache is remembered"""

    def test_sync_contracts_stores_it(self):
        source = ContractSource.objects.create(
            corporation_id=98000001, corporation_name="Test Corp"
        )
        expires = datetime(2026, 10, 27, 17, 55, 55, tzinfo=timezone.utc)
        fetched = FetchResult(contracts=[], expires=expires)

        with patch(f"{SYNC}.fetch_corporation_contracts", return_value=fetched):
            sync_contracts()

        source.refresh_from_db()
        self.assertEqual(source.esi_expires_at, expires)


class TestSyncContractsView(TestCase):
    """The button"""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.builder = make_user("builder", "builder_access")

    def _post(self, attempt, user=None):
        client = Client()  # fresh client: no messages left over from before
        client.force_login(user or self.builder)

        with patch(f"{VIEWS}.sync_now", return_value=attempt) as mock_sync:
            response = client.post(reverse("evebuilders:sync_contracts"))

        return response, mock_sync

    @staticmethod
    def _messages(response):
        return [(m.level, str(m.message)) for m in get_messages(response.wsgi_request)]

    def test_anonymous_and_users_without_access_are_sent_away(self):
        url = reverse("evebuilders:sync_contracts")
        nobody = make_user("nobody")

        with patch(f"{VIEWS}.sync_now") as mock_sync:
            self.assertEqual(self.client.post(url).status_code, 302)
            self.client.force_login(nobody)
            self.assertEqual(self.client.post(url).status_code, 302)

        mock_sync.assert_not_called()

    def test_get_is_not_allowed(self):
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:sync_contracts"))

        self.assertEqual(response.status_code, 405)

    def test_too_soon_is_a_warning(self):
        response, _mock = self._post(SyncAttempt(too_soon=True, wait_seconds=42))

        self.assertRedirects(
            response, reverse("evebuilders:my_orders"), fetch_redirect_response=False
        )
        level, text = self._messages(response)[0]
        self.assertEqual(level, constants.WARNING)
        self.assertIn("42", text)

    def test_an_error_is_shown(self):
        response, _mock = self._post(SyncAttempt(report=SyncReport(error="refused")))

        level, text = self._messages(response)[0]
        self.assertEqual(level, constants.ERROR)
        self.assertIn("refused", text)

    def test_changes_and_the_current_state_are_shown(self):
        report = SyncReport(
            seen=19,
            credited=1,
            credited_items=1,
            waiting_contracts=2,
            waiting_items=7,
            problem_contracts=1,
            expires=datetime(2026, 10, 27, 17, 55, 55, tzinfo=timezone.utc),
        )

        response, _mock = self._post(SyncAttempt(report=report))

        changes, state = self._messages(response)
        self.assertEqual(changes[0], constants.SUCCESS)
        self.assertIn("1 contract(s) credited (1 items)", changes[1])
        self.assertEqual(state[0], constants.INFO)
        self.assertIn("2 contract(s) wait for acceptance (7 items)", state[1])
        self.assertNotIn("UTC", state[1])
        self.assertIn("when ESI refreshes its data", state[1])

    def test_nothing_changed(self):
        response, _mock = self._post(SyncAttempt(report=SyncReport(seen=3)))

        changes, _state = self._messages(response)
        self.assertEqual(changes[0], constants.INFO)
        self.assertIn("Nothing changed", changes[1])

    def test_a_problem_contract_makes_the_message_a_warning(self):
        response, _mock = self._post(SyncAttempt(report=SyncReport(seen=3, invalid=1)))

        changes, _state = self._messages(response)
        self.assertEqual(changes[0], constants.WARNING)
        self.assertIn("cannot be counted", changes[1])


@override_settings(STORAGES=TEST_STORAGES)
class TestMyOrdersSyncButton(TestCase):
    """The button and the cache note on the page"""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.builder = make_user("builder", "builder_access")

    def test_button_is_shown_when_a_source_is_connected(self):
        ContractSource.objects.create(
            corporation_id=98000001, corporation_name="Test Corp"
        )
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:my_orders"))

        self.assertContains(response, reverse("evebuilders:sync_contracts"))
        self.assertContains(response, "have not been checked yet")

    def test_without_a_source_there_is_no_button(self):
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:my_orders"))

        self.assertNotContains(response, reverse("evebuilders:sync_contracts"))
        self.assertContains(response, "not connected yet")

    def test_the_cache_note_is_shown(self):
        ContractSource.objects.create(
            corporation_id=98000001,
            corporation_name="Test Corp",
            last_success_at=dj_timezone.now(),
            esi_expires_at=dj_timezone.now() + timedelta(minutes=3),
        )
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:my_orders"))

        self.assertContains(response, "The next automatic check is around")
