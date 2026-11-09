"""Old contracts and the time a builder took his order"""

# Standard Library
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

# Django
from django.utils import timezone

# AA EVE Builders
from evebuilders import reasons
from evebuilders.matching import Outcome
from evebuilders.models import ContractRecord, Order, OrderAssignment
from evebuilders.orders import create_order, take_order
from evebuilders.tests.test_matching import MatchingTestCase
from evebuilders.tests.test_sync import SyncTestCase

TAKEN = datetime(2026, 10, 20, 10, 0, tzinfo=dt_timezone.utc)
BEFORE = "2026-10-20T09:59:00Z"
AT = "2026-10-20T10:00:00Z"
AFTER = "2026-10-20T10:01:00Z"


def took_at(share, moment) -> None:
    """Say that the builder took his order at a moment"""

    OrderAssignment.objects.filter(pk=share.pk).update(created_at=moment)


class TestWhichContractsMatter(MatchingTestCase):
    """classify_contract looks only at what was made after taking the order"""

    def setUp(self):
        took_at(self.share, TAKEN)

    def test_a_contract_with_the_number_made_before_taking_is_not_a_delivery(self):
        verdict, loader = self._classify(self._contract(date_issued=BEFORE))

        self.assertEqual(verdict.outcome, Outcome.IGNORE)
        loader.assert_not_called()

    def test_a_contract_made_at_the_moment_of_taking_counts(self):
        verdict, _loader = self._classify(self._contract(date_issued=AT))

        self.assertEqual(verdict.outcome, Outcome.PENDING)

    def test_a_contract_made_after_taking_counts(self):
        verdict, _loader = self._classify(self._contract(date_issued=AFTER))

        self.assertEqual(verdict.outcome, Outcome.PENDING)

    def test_an_old_contract_without_a_number_is_ignored(self):
        verdict, _loader = self._classify(self._contract(title="", date_issued=BEFORE))

        self.assertEqual(verdict.outcome, Outcome.IGNORE)

    def test_a_new_contract_without_a_number_is_a_problem(self):
        verdict, _loader = self._classify(self._contract(title="", date_issued=AFTER))

        self.assertEqual(verdict.outcome, Outcome.INVALID)
        self.assertEqual(verdict.reason_code, reasons.NO_NUMBER)

    def test_old_and_new_contracts_with_two_numbers(self):
        title = f"{self.order.number} N20990101-1"

        old, _loader = self._classify(self._contract(title=title, date_issued=BEFORE))
        new, _loader = self._classify(self._contract(title=title, date_issued=AFTER))

        self.assertEqual(old.outcome, Outcome.IGNORE)
        self.assertEqual(new.reason_code, reasons.MANY_NUMBERS)

    def test_old_and_new_contracts_with_an_unknown_number(self):
        old, _loader = self._classify(
            self._contract(title="N20990101-1", date_issued=BEFORE)
        )
        new, _loader = self._classify(
            self._contract(title="N20990101-1", date_issued=AFTER)
        )

        self.assertEqual(old.outcome, Outcome.IGNORE)
        self.assertEqual(new.reason_code, reasons.UNKNOWN_ORDER)

    def test_somebody_with_nothing_left_to_deliver_is_not_watched(self):
        OrderAssignment.objects.filter(pk=self.share.pk).update(credited=5)

        verdict, _loader = self._classify(self._contract(title="", date_issued=AFTER))

        self.assertEqual(verdict.outcome, Outcome.IGNORE)

    def test_an_order_that_is_not_open_does_not_count_as_something_to_deliver(self):
        Order.objects.filter(pk=self.order.pk).update(status=Order.Status.CANCELLED)

        verdict, _loader = self._classify(self._contract(title="", date_issued=AFTER))

        self.assertEqual(verdict.outcome, Outcome.IGNORE)

    def test_the_oldest_open_order_sets_the_start(self):
        second = create_order(
            user=self.manager,
            eve_type=self.eve_type,
            quantity=10,
            unit_price=Decimal("100.00"),
            due_date=timezone.localdate() + timedelta(days=7),
        )
        take_order(user=self.builder, order_id=second.pk, quantity=5)
        second_share = OrderAssignment.objects.get(order=second, builder=self.builder)
        took_at(second_share, TAKEN + timedelta(days=2))

        # Between the two: after the first order was taken, before the second
        verdict, _loader = self._classify(
            self._contract(title="", date_issued="2026-10-21T10:00:00Z")
        )

        self.assertEqual(verdict.reason_code, reasons.NO_NUMBER)

    def test_somebody_who_is_not_a_builder_is_ignored(self):
        manager_id = self.manager.profile.main_character.character_id

        verdict, _loader = self._classify(
            self._contract(title="", issuer_id=manager_id, date_issued=AFTER)
        )

        self.assertEqual(verdict.outcome, Outcome.IGNORE)

    def test_a_character_that_is_not_on_auth_is_ignored(self):
        verdict, _loader = self._classify(
            self._contract(title="N20990101-1", issuer_id=1, date_issued=AFTER)
        )

        self.assertEqual(verdict.outcome, Outcome.IGNORE)


class TestTheSyncAndOldContracts(SyncTestCase):
    """What the sync does with them"""

    def setUp(self):
        took_at(self.share, TAKEN)

    def test_an_old_contract_leaves_no_record(self):
        report = self._process([self._contract(title="", date_issued=BEFORE)])

        self.assertEqual(report.invalid, 0)
        self.assertFalse(ContractRecord.objects.exists())

    def test_a_new_contract_without_a_number_is_recorded_as_a_problem(self):
        report = self._process([self._contract(title="", date_issued=AFTER)])

        record = ContractRecord.objects.get(contract_id=1001)
        self.assertEqual(report.invalid, 1)
        self.assertEqual(record.state, ContractRecord.State.INVALID)
        self.assertEqual(record.reason_code, reasons.NO_NUMBER)

    def test_a_problem_that_is_still_one_stays(self):
        contract = self._contract(title="", date_issued=AFTER)

        self._process([contract])
        self._process([contract])

        self.assertEqual(
            ContractRecord.objects.get(contract_id=1001).state,
            ContractRecord.State.INVALID,
        )

    def test_a_problem_record_of_an_old_contract_is_forgotten(self):
        # What an earlier version of the plugin recorded for an old contract
        ContractRecord.objects.create(
            contract_id=1001,
            issuer_character_id=self.issuer_id,
            state=ContractRecord.State.INVALID,
            reason="The contract title has no order number.",
            reason_code=reasons.NO_NUMBER,
        )

        self._process([self._contract(title="", date_issued=BEFORE)])

        self.assertFalse(ContractRecord.objects.filter(contract_id=1001).exists())

    def test_credited_and_waiting_records_are_not_forgotten(self):
        credited = ContractRecord.objects.create(
            contract_id=2001,
            order=self.order,
            assignment=self.share,
            issuer_character_id=self.issuer_id,
            quantity=1,
            state=ContractRecord.State.CREDITED,
        )
        waiting = ContractRecord.objects.create(
            contract_id=2002,
            order=self.order,
            assignment=self.share,
            issuer_character_id=self.issuer_id,
            quantity=1,
            state=ContractRecord.State.OUTSTANDING,
        )

        # Contracts that are of no interest now (not item exchange)
        self._process(
            [
                self._contract(contract_id=2001, type="courier"),
                self._contract(contract_id=2002, type="courier"),
            ]
        )

        self.assertTrue(ContractRecord.objects.filter(pk=credited.pk).exists())
        self.assertTrue(ContractRecord.objects.filter(pk=waiting.pk).exists())
