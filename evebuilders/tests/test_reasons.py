"""Reasons why a contract cannot be counted: codes, texts and what is stored"""

# Django
from django.test import SimpleTestCase, TestCase
from django.utils import translation

# AA EVE Builders
from evebuilders import reasons
from evebuilders.matching import Outcome
from evebuilders.models import ContractRecord, Order
from evebuilders.reasons import english, reason_fields, reason_text
from evebuilders.tests.test_matching import MatchingTestCase
from evebuilders.tests.test_sync import SyncTestCase

PRICE = "The price must be 500.00 ISK for 5 items."


class TestReasonText(SimpleTestCase):
    """reason_text and friends"""

    def test_every_code_has_a_text_with_its_parameters(self):
        cases = [
            (reasons.CLOSED, {"status": "deleted"}, "The contract is deleted."),
            (reasons.NO_NUMBER, {}, "The contract title has no order number."),
            (
                reasons.MANY_NUMBERS,
                {},
                "The contract title has more than one order number.",
            ),
            (
                reasons.UNKNOWN_ORDER,
                {"number": "N20990101-1"},
                "There is no order with the number N20990101-1.",
            ),
            (
                reasons.NOT_ON_ACCOUNT,
                {},
                "The character that made the contract is not on an Auth account.",
            ),
            (reasons.NOT_TAKEN, {}, "The builder has not taken this order."),
            (
                reasons.NO_ITEM,
                {"item": "Punisher"},
                "The contract does not contain Punisher.",
            ),
            (reasons.WRONG_PRICE, {"expected": "500.00", "quantity": 5}, PRICE),
            (
                reasons.TOO_MANY,
                {"available": 2, "quantity": 5},
                "Only 2 items are left to deliver, the contract has 5.",
            ),
            (
                reasons.NOT_AVAILABLE,
                {},
                "The items are no longer available to deliver.",
            ),
            (reasons.ORDER_CANCELLED, {}, "The order was cancelled."),
        ]

        for code, data, expected in cases:
            with self.subTest(code=code):
                self.assertEqual(reason_text(code, data), expected)

    def test_no_code_or_an_unknown_one_gives_no_text(self):
        self.assertEqual(reason_text(""), "")
        self.assertEqual(reason_text("nonsense", {"a": 1}), "")

    def test_missing_parameters_do_not_crash(self):
        self.assertTrue(reason_text(reasons.WRONG_PRICE, {}))
        self.assertTrue(reason_text(reasons.TOO_MANY, None))

    def test_english_ignores_the_language_of_the_request(self):
        with translation.override("ru"):
            text = english(reasons.NO_NUMBER)

        self.assertEqual(text, "The contract title has no order number.")

    def test_the_fields_of_a_record(self):
        fields = reason_fields(
            reasons.WRONG_PRICE, {"expected": "500.00", "quantity": 5}
        )

        self.assertEqual(
            fields,
            {
                "reason": PRICE,
                "reason_code": reasons.WRONG_PRICE,
                "reason_data": {"expected": "500.00", "quantity": 5},
            },
        )


class TestContractRecordReason(TestCase):
    """What a record does with its reason"""

    def _record(self, **extra):
        return ContractRecord.objects.create(
            contract_id=1, issuer_character_id=1, **extra
        )

    def test_no_reason_means_no_code(self):
        record = self._record(**reason_fields(reasons.NO_NUMBER))

        record.reason = ""
        record.save()
        record.refresh_from_db()

        self.assertEqual(record.reason_code, "")
        self.assertEqual(record.reason_data, {})

    def test_the_code_and_the_data_survive_the_database(self):
        record = self._record(
            **reason_fields(reasons.WRONG_PRICE, {"expected": "500.00", "quantity": 5})
        )

        record.refresh_from_db()

        self.assertEqual(record.reason_code, reasons.WRONG_PRICE)
        self.assertEqual(record.reason_data, {"expected": "500.00", "quantity": 5})
        self.assertEqual(record.reason_in("en"), PRICE)
        self.assertEqual(record.reason_text, PRICE)

    def test_an_older_record_shows_its_text(self):
        record = self._record(reason="Old English text")

        self.assertEqual(record.reason_text, "Old English text")
        self.assertEqual(record.reason_in("ru"), "Old English text")


class TestVerdictCodes(MatchingTestCase):
    """The codes that classify_contract gives"""

    def test_a_missing_number(self):
        verdict, _loader = self._classify(self._contract(title=""))

        self.assertEqual(verdict.reason_code, reasons.NO_NUMBER)
        self.assertEqual(verdict.reason, "The contract title has no order number.")

    def test_an_unknown_order(self):
        verdict, _loader = self._classify(self._contract(title="N20990101-1"))

        self.assertEqual(verdict.reason_code, reasons.UNKNOWN_ORDER)
        self.assertEqual(verdict.reason_data, {"number": "N20990101-1"})

    def test_a_wrong_item(self):
        verdict, _loader = self._classify(items=self._items(type_id=999))

        self.assertEqual(verdict.reason_code, reasons.NO_ITEM)
        self.assertEqual(verdict.reason_data, {"item": "Punisher"})

    def test_a_wrong_price(self):
        verdict, _loader = self._classify(self._contract(price=499.0))

        self.assertEqual(verdict.reason_code, reasons.WRONG_PRICE)
        self.assertEqual(verdict.reason_data, {"expected": "500.00", "quantity": 5})
        self.assertEqual(verdict.reason, PRICE)

    def test_too_many_items(self):
        verdict, _loader = self._classify(
            self._contract(price=600.0), items=self._items(quantity=6)
        )

        self.assertEqual(verdict.reason_code, reasons.TOO_MANY)
        self.assertEqual(verdict.reason_data, {"available": 5, "quantity": 6})

    def test_an_ended_contract(self):
        self._record(ContractRecord.State.OUTSTANDING)

        verdict, _loader = self._classify(self._contract(status="deleted"))

        self.assertEqual(verdict.outcome, Outcome.CLOSED)
        self.assertEqual(verdict.reason_code, reasons.CLOSED)
        self.assertEqual(verdict.reason_data, {"status": "deleted"})

    def test_a_cancelled_order(self):
        Order.objects.filter(pk=self.order.pk).update(status=Order.Status.CANCELLED)

        verdict, _loader = self._classify()

        self.assertEqual(verdict.reason_code, reasons.ORDER_CANCELLED)

    def test_a_good_contract_has_no_reason(self):
        verdict, _loader = self._classify()

        self.assertEqual(verdict.reason_code, "")
        self.assertEqual(verdict.reason, "")


class TestTheSyncStoresTheCodes(SyncTestCase):
    """What the sync writes into the records"""

    def _record(self):
        return ContractRecord.objects.get(contract_id=1001)

    def test_the_code_the_data_and_the_english_text_are_stored(self):
        self._process([self._contract(price=499.0)])

        record = self._record()

        self.assertEqual(record.state, ContractRecord.State.INVALID)
        self.assertEqual(record.reason_code, reasons.WRONG_PRICE)
        self.assertEqual(record.reason_data, {"expected": "500.00", "quantity": 5})
        self.assertEqual(record.reason, PRICE)

    def test_the_stored_text_is_english_even_in_a_russian_request(self):
        with translation.override("ru"):
            self._process([self._contract(price=499.0)])

        self.assertEqual(self._record().reason, PRICE)

    def test_a_changed_reason_replaces_the_code(self):
        self._process([self._contract(price=499.0)])

        self._process([self._contract(title="")])

        self.assertEqual(self._record().reason_code, reasons.NO_NUMBER)

    def test_a_contract_that_became_valid_has_no_reason(self):
        self._process([self._contract(price=499.0)])

        self._process([self._contract()])

        record = self._record()
        self.assertEqual(record.state, ContractRecord.State.OUTSTANDING)
        self.assertEqual(record.reason, "")
        self.assertEqual(record.reason_code, "")
        self.assertEqual(record.reason_data, {})
