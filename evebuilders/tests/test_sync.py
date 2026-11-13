"""Applying contract verdicts (ESI is mocked out)"""

# Standard Library
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch

# Third Party
# EVE Universe
from eveuniverse.models import EveCategory, EveGroup, EveType

# Django
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone as dj_timezone

# AA EVE Builders
from evebuilders.contracts import EsiTokenError, EsiUnavailable, FetchResult
from evebuilders.matching import Outcome, Verdict
from evebuilders.models import (
    ContractRecord,
    ContractSource,
    Order,
    OrderAssignment,
    OrderEvent,
)
from evebuilders.orders import create_order, releasable_quantity, take_order
from evebuilders.sync import SyncReport, process_contracts, sync_contracts
from evebuilders.tests.test_views import make_user

SYNC = "evebuilders.sync"
COMMAND = "evebuilders.management.commands.evebuilders_sync_contracts"


class SyncTestCase(TestCase):
    """An order of 10 at 100 ISK, a builder who took 5, and an acceptor"""

    @classmethod
    def setUpTestData(cls) -> None:
        category = EveCategory.objects.create(id=6, name="Ship", published=True)
        group = EveGroup.objects.create(
            id=25, name="Frigate", eve_category=category, published=True
        )
        cls.eve_type = EveType.objects.create(
            id=597, name="Punisher", eve_group=group, published=True
        )
        cls.manager = make_user("manager", "admin_access")
        cls.builder = make_user("builder", "builder_access")
        cls.acceptor = make_user("acceptor", "builder_access")
        cls.corporation_id = 98000001
        cls.order = create_order(
            user=cls.manager,
            eve_type=cls.eve_type,
            quantity=10,
            unit_price=Decimal("100.00"),
            due_date=dj_timezone.localdate() + timedelta(days=7),
        )
        take_order(user=cls.builder, order_id=cls.order.pk, quantity=5)
        cls.share = OrderAssignment.objects.get(order=cls.order, builder=cls.builder)
        # The builder took the order well before the dates of the test contracts
        OrderAssignment.objects.filter(pk=cls.share.pk).update(
            created_at=datetime(2026, 10, 1, tzinfo=timezone.utc)
        )
        cls.share.refresh_from_db()
        cls.issuer_id = cls.builder.profile.main_character.character_id
        cls.acceptor_id = cls.acceptor.profile.main_character.character_id

    def _contract(self, **overrides):
        contract = {
            "contract_id": 1001,
            "type": "item_exchange",
            "status": "outstanding",
            "assignee_id": self.corporation_id,
            "issuer_id": self.issuer_id,
            "acceptor_id": 0,
            "title": self.order.number,
            "price": 500.0,
            "date_issued": "2026-10-27T10:00:00Z",
            "date_expired": "2099-01-01T00:00:00Z",
        }
        contract.update(overrides)

        return contract

    @staticmethod
    def _items(quantity=5, type_id=597):
        return [
            {
                "record_id": 1,
                "type_id": type_id,
                "quantity": quantity,
                "is_included": True,
            }
        ]

    def _process(self, contracts, items=None, loader=None):
        loader = loader or MagicMock(
            return_value=items if items is not None else self._items()
        )

        return process_contracts(
            contracts, corporation_id=self.corporation_id, items_loader=loader
        )

    def _finished(self, **overrides):
        return self._contract(
            status="finished",
            acceptor_id=self.acceptor_id,
            date_completed="2026-10-27T11:00:00Z",
            **overrides,
        )

    def _events(self, kind):
        return OrderEvent.objects.filter(kind=kind).count()


class TestProcessContracts(SyncTestCase):
    """process_contracts"""

    def test_a_valid_contract_is_recorded_once(self):
        report = self._process([self._contract()])

        record = ContractRecord.objects.get(contract_id=1001)
        self.assertEqual(report.pending, 1)
        self.assertEqual(record.state, ContractRecord.State.OUTSTANDING)
        self.assertEqual(record.order, self.order)
        self.assertEqual(record.assignment, self.share)
        self.assertEqual(record.quantity, 5)
        self.assertEqual(record.price, Decimal("500.00"))
        self.assertEqual(record.title, self.order.number)
        self.assertEqual(record.issuer_character_id, self.issuer_id)
        self.assertEqual(self._events(OrderEvent.Kind.CONTRACT_FOUND), 1)

        again = self._process([self._contract()])

        self.assertEqual(again.pending, 0)
        self.assertEqual(ContractRecord.objects.count(), 1)
        self.assertEqual(self._events(OrderEvent.Kind.CONTRACT_FOUND), 1)

    def test_an_accepted_contract_is_credited_once(self):
        report = self._process([self._finished()])

        record = ContractRecord.objects.get(contract_id=1001)
        self.share.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(report.credited, 1)
        self.assertEqual(report.credited_items, 5)
        self.assertEqual(self.share.credited, 5)
        self.assertEqual(record.state, ContractRecord.State.CREDITED)
        self.assertEqual(record.acceptor_character_id, self.acceptor_id)
        self.assertEqual(record.acceptor_user, self.acceptor)
        self.assertEqual(
            record.completed_at, datetime(2026, 10, 27, 11, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(self.order.status, Order.Status.IN_PROGRESS)
        self.assertEqual(self._events(OrderEvent.Kind.CREDITED), 1)

        again = self._process([self._finished()])

        self.share.refresh_from_db()
        self.assertEqual(again.credited, 0)
        self.assertEqual(self.share.credited, 5)
        self.assertEqual(self._events(OrderEvent.Kind.CREDITED), 1)

    def test_a_waiting_contract_that_gets_accepted_is_credited(self):
        self._process([self._contract()])

        report = self._process([self._finished()])

        self.share.refresh_from_db()
        self.assertEqual(report.credited, 1)
        self.assertEqual(self.share.credited, 5)
        self.assertEqual(ContractRecord.objects.count(), 1)
        self.assertEqual(
            ContractRecord.objects.get().state, ContractRecord.State.CREDITED
        )

    def test_the_last_delivery_completes_the_order(self):
        order = create_order(
            user=self.manager,
            eve_type=self.eve_type,
            quantity=5,
            unit_price=Decimal("100.00"),
            due_date=dj_timezone.localdate() + timedelta(days=7),
        )
        take_order(user=self.builder, order_id=order.pk, quantity=5)

        self._process(
            [self._finished(title=order.number, date_issued="2099-01-01T00:00:00Z")]
        )

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.COMPLETED)

    def test_an_invalid_contract_is_recorded_with_its_reason(self):
        report = self._process([self._contract(price=499.0)])

        record = ContractRecord.objects.get(contract_id=1001)
        self.assertEqual(report.invalid, 1)
        self.assertEqual(record.state, ContractRecord.State.INVALID)
        self.assertIn("price", record.reason)
        self.assertEqual(self._events(OrderEvent.Kind.CONTRACT_INVALID), 1)

        again = self._process([self._contract(price=499.0)])

        self.assertEqual(again.invalid, 0)
        self.assertEqual(self._events(OrderEvent.Kind.CONTRACT_INVALID), 1)

    def test_an_invalid_contract_without_an_order_has_no_history_entry(self):
        self._process([self._contract(title="N20990101-1")])

        record = ContractRecord.objects.get(contract_id=1001)
        self.assertEqual(record.state, ContractRecord.State.INVALID)
        self.assertIsNone(record.order)
        self.assertEqual(self._events(OrderEvent.Kind.CONTRACT_INVALID), 0)

    def test_a_contract_that_ended_is_closed(self):
        self._process([self._contract()])
        self.assertEqual(releasable_quantity(self.share), 0)

        report = self._process([self._contract(status="deleted")])

        self.assertEqual(report.closed, 1)
        self.assertEqual(
            ContractRecord.objects.get().state, ContractRecord.State.CLOSED
        )
        self.assertEqual(self._events(OrderEvent.Kind.CONTRACT_CLOSED), 1)
        self.assertEqual(releasable_quantity(self.share), 5)

    def test_contracts_are_processed_from_the_oldest(self):
        older = self._contract(
            contract_id=1001, price=300.0, date_issued="2026-10-27T10:00:00Z"
        )
        newer = self._contract(
            contract_id=1002, price=300.0, date_issued="2026-10-27T11:00:00Z"
        )

        # Given newest first, but the builder has only 5 items for 3 + 3
        self._process([newer, older], items=self._items(quantity=3))

        self.assertEqual(
            ContractRecord.objects.get(contract_id=1001).state,
            ContractRecord.State.OUTSTANDING,
        )
        self.assertEqual(
            ContractRecord.objects.get(contract_id=1002).state,
            ContractRecord.State.INVALID,
        )

    def test_foreign_contracts_leave_no_trace(self):
        report = self._process([self._contract(assignee_id=12345)])

        self.assertEqual(report.seen, 1)
        self.assertEqual(report.pending + report.credited + report.invalid, 0)
        self.assertFalse(ContractRecord.objects.exists())

    def test_a_problem_with_the_items_skips_only_that_contract(self):
        def loader(contract_id):
            if contract_id == 1001:
                raise EsiUnavailable("down")
            return self._items(quantity=2)

        report = self._process(
            [
                self._contract(contract_id=1001),
                self._contract(contract_id=1002, price=200.0),
            ],
            loader=loader,
        )

        self.assertEqual(report.skipped, 1)
        self.assertEqual(report.pending, 1)
        self.assertEqual(ContractRecord.objects.get().contract_id, 1002)

    def test_a_token_problem_stops_everything(self):
        loader = MagicMock(side_effect=EsiTokenError("refused"))

        with self.assertRaises(EsiTokenError):
            self._process([self._contract()], loader=loader)

    def test_nothing_is_credited_when_the_items_are_gone(self):
        # A waiting contract already uses all 5 items of the share
        ContractRecord.objects.create(
            contract_id=2002,
            order=self.order,
            assignment=self.share,
            issuer_character_id=self.issuer_id,
            quantity=5,
            state=ContractRecord.State.OUTSTANDING,
        )
        verdict = Verdict(
            Outcome.CREDIT,
            order=self.order,
            share=self.share,
            quantity=5,
            price=Decimal("500"),
        )

        with patch(f"{SYNC}.classify_contract", return_value=verdict):
            report = self._process([self._finished()])

        self.share.refresh_from_db()
        self.assertEqual(report.credited, 0)
        self.assertEqual(self.share.credited, 0)
        self.assertEqual(
            ContractRecord.objects.get(contract_id=1001).state,
            ContractRecord.State.INVALID,
        )


class TestSyncContracts(SyncTestCase):
    """sync_contracts"""

    def setUp(self):
        self.source = ContractSource.objects.create(
            corporation_id=self.corporation_id, corporation_name="Test Corp"
        )

    def test_success_is_remembered_on_the_source(self):
        expires = datetime(2026, 10, 27, 17, 12, 55, tzinfo=timezone.utc)
        fetched = FetchResult(contracts=[self._contract()], expires=expires)

        with patch(f"{SYNC}.fetch_corporation_contracts", return_value=fetched):
            with patch(f"{SYNC}.fetch_contract_items", return_value=self._items()):
                report = sync_contracts()

        self.source.refresh_from_db()
        self.assertEqual(report.pending, 1)
        self.assertEqual(report.expires, expires)
        self.assertEqual(report.error, "")
        self.assertIsNotNone(self.source.last_sync_at)
        self.assertIsNotNone(self.source.last_success_at)
        self.assertEqual(self.source.last_error, "")
        self.assertTrue(self.source.token_ok)

    def test_a_refused_token_is_remembered(self):
        with patch(
            f"{SYNC}.fetch_corporation_contracts", side_effect=EsiTokenError("refused")
        ):
            report = sync_contracts()

        self.source.refresh_from_db()
        self.assertEqual(report.error, "refused")
        self.assertFalse(self.source.token_ok)
        self.assertEqual(self.source.last_error, "refused")
        self.assertIsNone(self.source.last_success_at)

    def test_esi_being_down_keeps_the_token_ok(self):
        with patch(
            f"{SYNC}.fetch_corporation_contracts", side_effect=EsiUnavailable("down")
        ):
            report = sync_contracts()

        self.source.refresh_from_db()
        self.assertEqual(report.error, "down")
        self.assertTrue(self.source.token_ok)
        self.assertEqual(self.source.last_error, "down")

    def test_no_source(self):
        ContractSource.objects.all().delete()

        report = sync_contracts()

        self.assertTrue(report.error)

    def _sync(self, contracts):
        fetched = FetchResult(contracts=contracts, expires=None)

        with patch(f"{SYNC}.fetch_corporation_contracts", return_value=fetched):
            with patch(f"{SYNC}.fetch_contract_items", return_value=self._items()):
                return sync_contracts()

    def test_the_report_shows_what_waits_even_when_nothing_changed(self):
        first = self._sync([self._contract()])
        second = self._sync([self._contract()])

        self.assertEqual(first.pending, 1)
        self.assertTrue(first.changed)
        self.assertEqual(second.pending, 0)
        self.assertFalse(second.changed)
        # Nothing changed, but the state is still reported
        self.assertEqual(second.waiting_contracts, 1)
        self.assertEqual(second.waiting_items, 5)

    def test_problem_contracts_are_counted_in_every_report(self):
        first = self._sync([self._contract(price=499.0)])
        second = self._sync([self._contract(price=499.0)])

        self.assertEqual(first.invalid, 1)
        self.assertEqual(second.invalid, 0)
        self.assertEqual(second.problem_contracts, 1)
        self.assertEqual(second.waiting_contracts, 0)


class TestSyncContractsCommand(TestCase):
    """evebuilders_sync_contracts"""

    def test_prints_the_report(self):
        out = StringIO()
        report = SyncReport(seen=3, credited=1, credited_items=5)

        with patch(f"{COMMAND}.sync_contracts", return_value=report):
            call_command("evebuilders_sync_contracts", stdout=out)

        self.assertIn("Contracts seen: 3", out.getvalue())
        self.assertIn("credited: 1 (5 items)", out.getvalue())

    def test_an_error_becomes_a_command_error(self):
        with patch(
            f"{COMMAND}.sync_contracts", return_value=SyncReport(error="refused")
        ):
            with self.assertRaises(CommandError):
                call_command("evebuilders_sync_contracts", stdout=StringIO())

    def test_reports_the_current_state_and_the_cache_note(self):
        out = StringIO()
        report = SyncReport(
            seen=19,
            waiting_contracts=1,
            waiting_items=1,
            problem_contracts=1,
            expires=datetime(2026, 10, 27, 17, 55, 55, tzinfo=timezone.utc),
        )

        with patch(f"{COMMAND}.sync_contracts", return_value=report):
            call_command("evebuilders_sync_contracts", stdout=out)

        text = out.getvalue()
        self.assertIn("Nothing changed", text)
        self.assertIn("1 contract(s) waiting for acceptance (1 items)", text)
        self.assertIn("1 problem contract(s)", text)
        self.assertIn("17:55:55 UTC", text)

    def test_no_nothing_changed_note_after_changes(self):
        out = StringIO()
        report = SyncReport(seen=1, credited=1, credited_items=1)

        with patch(f"{COMMAND}.sync_contracts", return_value=report):
            call_command("evebuilders_sync_contracts", stdout=out)

        self.assertNotIn("Nothing changed", out.getvalue())
