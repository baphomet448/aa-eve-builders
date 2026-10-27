"""Reading the corporation contracts from ESI (ESI is mocked out)"""

# Standard Library
from datetime import datetime, timezone
from io import StringIO
from unittest.mock import MagicMock, patch

# Third Party
import requests

# Django
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

# Alliance Auth (External Libs)
from esi.models import Token

# AA EVE Builders
from evebuilders.contracts import (
    EsiTokenError,
    EsiUnavailable,
    connect_source,
    fetch_contract_items,
    fetch_corporation_contracts,
)
from evebuilders.models import ContractSource
from evebuilders.tests.test_contracts_source import make_token
from evebuilders.tests.test_views import make_user

GET = "evebuilders.contracts.requests.get"
COMMAND = "evebuilders.management.commands.evebuilders_show_contracts"


def fake_response(
    status=200, data=None, pages=1, expires="Tue, 27 Oct 2026 17:12:55 GMT"
):
    """A stand-in for a requests response"""

    response = MagicMock()
    response.status_code = status
    response.text = "body"
    response.json.return_value = data if data is not None else []
    response.headers = {"X-Pages": str(pages)}
    if expires:
        response.headers["Expires"] = expires

    return response


class FetchTestCase(TestCase):
    """A connected source and a token that always has an access token"""

    @classmethod
    def setUpTestData(cls) -> None:
        manager = make_user("manager", "manage_access")
        token = make_token(manager, manager.profile.main_character.character_id)
        cls.source = connect_source(user=manager, token=token)

    def setUp(self):
        patcher = patch.object(Token, "valid_access_token", return_value="access")
        patcher.start()
        self.addCleanup(patcher.stop)


class TestFetchCorporationContracts(FetchTestCase):
    """fetch_corporation_contracts"""

    @patch(GET)
    def test_one_page(self, mock_get):
        mock_get.return_value = fake_response(data=[{"contract_id": 1}])

        result = fetch_corporation_contracts(self.source)

        self.assertEqual(result.contracts, [{"contract_id": 1}])
        self.assertEqual(
            result.expires, datetime(2026, 10, 27, 17, 12, 55, tzinfo=timezone.utc)
        )
        args, kwargs = mock_get.call_args
        self.assertEqual(
            args[0], "https://esi.evetech.net/latest/corporations/98000001/contracts/"
        )
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer access")
        self.assertEqual(kwargs["params"], {"page": 1})

    @patch(GET)
    def test_all_pages_are_read(self, mock_get):
        mock_get.side_effect = [
            fake_response(data=[{"contract_id": 1}], pages=2),
            fake_response(data=[{"contract_id": 2}], pages=2),
        ]

        result = fetch_corporation_contracts(self.source)

        self.assertEqual(result.contracts, [{"contract_id": 1}, {"contract_id": 2}])
        pages = [call.kwargs["params"]["page"] for call in mock_get.call_args_list]
        self.assertEqual(pages, [1, 2])

    @patch(GET)
    def test_missing_expires_header(self, mock_get):
        mock_get.return_value = fake_response(expires=None)

        self.assertIsNone(fetch_corporation_contracts(self.source).expires)

    @patch(GET)
    def test_refused_token(self, mock_get):
        for status in (401, 403):
            with self.subTest(status=status):
                mock_get.return_value = fake_response(status=status)

                with self.assertRaises(EsiTokenError):
                    fetch_corporation_contracts(self.source)

    @patch(GET)
    def test_esi_problems(self, mock_get):
        for status in (420, 500, 503):
            with self.subTest(status=status):
                mock_get.return_value = fake_response(status=status)

                with self.assertRaises(EsiUnavailable):
                    fetch_corporation_contracts(self.source)

    @patch(GET, side_effect=requests.ConnectionError("no network"))
    def test_network_problem(self, _mock_get):
        with self.assertRaises(EsiUnavailable):
            fetch_corporation_contracts(self.source)

    def test_unusable_token(self):
        with patch.object(
            Token, "valid_access_token", side_effect=RuntimeError("revoked")
        ):
            with self.assertRaises(EsiTokenError):
                fetch_corporation_contracts(self.source)

    def test_source_without_a_token(self):
        ContractSource.objects.update(token=None)
        source = ContractSource.get_solo()

        with self.assertRaises(EsiTokenError):
            fetch_corporation_contracts(source)


class TestFetchContractItems(FetchTestCase):
    """fetch_contract_items"""

    @patch(GET)
    def test_returns_the_items(self, mock_get):
        items = [{"type_id": 588, "quantity": 1, "is_included": True}]
        mock_get.return_value = fake_response(data=items)

        self.assertEqual(fetch_contract_items(self.source, 777), items)

        self.assertEqual(
            mock_get.call_args.args[0],
            "https://esi.evetech.net/latest/corporations/98000001/contracts/777/items/",
        )


class TestShowContractsCommand(FetchTestCase):
    """evebuilders_show_contracts"""

    @staticmethod
    def _contracts():
        return [
            {
                "contract_id": 1,
                "status": "finished",
                "type": "item_exchange",
                "issuer_id": 5,
                "assignee_id": 98000001,
                "acceptor_id": 6,
                "price": 1.0,
                "title": "old",
                "date_issued": "2026-09-01T10:00:00Z",
            },
            {
                "contract_id": 2,
                "status": "outstanding",
                "type": "item_exchange",
                "issuer_id": 5,
                "assignee_id": 98000001,
                "acceptor_id": 0,
                "price": 100.0,
                "title": "N20261027-1",
                "date_issued": "2026-10-27T10:00:00Z",
            },
        ]

    def test_shows_the_newest_first(self):
        out = StringIO()
        result = MagicMock(contracts=self._contracts(), expires=None)

        with patch(f"{COMMAND}.fetch_corporation_contracts", return_value=result):
            call_command("evebuilders_show_contracts", stdout=out)

        lines = out.getvalue().splitlines()
        self.assertIn("2 contracts", lines[0])
        self.assertTrue(lines[1].startswith("2 outstanding"))
        self.assertTrue(lines[2].startswith("1 finished"))

    def test_items_are_shown_on_request(self):
        out = StringIO()
        result = MagicMock(contracts=self._contracts(), expires=None)
        items = [{"type_id": 588, "quantity": 3, "is_included": True}]

        with patch(f"{COMMAND}.fetch_corporation_contracts", return_value=result):
            with patch(f"{COMMAND}.fetch_contract_items", return_value=items):
                call_command("evebuilders_show_contracts", "--items", stdout=out)

        self.assertIn("type_id=588 quantity=3 included=True", out.getvalue())

    def test_no_source(self):
        ContractSource.objects.all().delete()

        with self.assertRaises(CommandError):
            call_command("evebuilders_show_contracts", stdout=StringIO())

    def test_esi_error_becomes_a_command_error(self):
        with patch(
            f"{COMMAND}.fetch_corporation_contracts",
            side_effect=EsiUnavailable("down"),
        ):
            with self.assertRaises(CommandError):
                call_command("evebuilders_show_contracts", stdout=StringIO())