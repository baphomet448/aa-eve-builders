"""Contract classification tests (ESI is not involved)"""

# Standard Library
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock

# Third Party
# EVE Universe
from eveuniverse.models import EveCategory, EveGroup, EveType

# Django
from django.test import TestCase
from django.utils import timezone

# AA EVE Builders
from evebuilders.matching import Outcome, classify_contract, find_order_numbers
from evebuilders.models import ContractRecord, OrderAssignment
from evebuilders.orders import create_order, take_order
from evebuilders.tests.test_views import make_user


class TestFindOrderNumbers(TestCase):
    """find_order_numbers"""

    def test_finds_numbers_in_titles(self):
        self.assertEqual(find_order_numbers("N20261027-2"), {"N20261027-2"})
        self.assertEqual(
            find_order_numbers("N20261027-2 Amarr Shuttle"), {"N20261027-2"}
        )
        self.assertEqual(
            find_order_numbers("N20261027-2, N20261027-3"),
            {"N20261027-2", "N20261027-3"},
        )

    def test_longer_counters_are_not_confused(self):
        self.assertEqual(find_order_numbers("N20261027-22"), {"N20261027-22"})

    def test_things_that_are_not_order_numbers(self):
        for title in (
            "",
            None,
            "HLOP TYPHOON",
            "XN20261027-2",
            "N2026102-2",
            "N20261027",
        ):
            with self.subTest(title=title):
                self.assertEqual(find_order_numbers(title), set())


class MatchingTestCase(TestCase):
    """An order of 10 at 100 ISK, a builder who took 5, and ESI-like contracts"""

    @classmethod
    def setUpTestData(cls) -> None:
        category = EveCategory.objects.create(id=6, name="Ship", published=True)
        group = EveGroup.objects.create(
            id=25, name="Frigate", eve_category=category, published=True
        )
        cls.eve_type = EveType.objects.create(
            id=597, name="Punisher", eve_group=group, published=True
        )
        cls.manager = make_user("manager", "manage_access")
        cls.builder = make_user("builder", "builder_access")
        cls.corporation_id = 98000001
        cls.order = create_order(
            user=cls.manager,
            eve_type=cls.eve_type,
            quantity=10,
            unit_price=Decimal("100.00"),
            due_date=timezone.localdate() + timedelta(days=7),
        )
        take_order(user=cls.builder, order_id=cls.order.pk, quantity=5)
        cls.share = OrderAssignment.objects.get(order=cls.order, builder=cls.builder)
        cls.issuer_id = cls.builder.profile.main_character.character_id

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
    def _items(quantity=5, type_id=597, included=True):
        return [
            {
                "record_id": 1,
                "type_id": type_id,
                "quantity": quantity,
                "is_included": included,
            }
        ]

    def _classify(self, contract=None, items=None):
        loader = MagicMock(return_value=items if items is not None else self._items())
        verdict = classify_contract(
            contract or self._contract(),
            corporation_id=self.corporation_id,
            items_loader=loader,
        )

        return verdict, loader

    def _record(self, state, quantity=5, contract_id=1001):
        return ContractRecord.objects.create(
            contract_id=contract_id,
            order=self.order,
            assignment=self.share,
            issuer_character_id=self.issuer_id,
            quantity=quantity,
            price=Decimal("100") * quantity,
            state=state,
        )


class TestValidContracts(MatchingTestCase):
    """Contracts that can be counted"""

    def test_outstanding_contract_is_pending(self):
        verdict, loader = self._classify()

        self.assertEqual(verdict.outcome, Outcome.PENDING)
        self.assertEqual(verdict.quantity, 5)
        self.assertEqual(verdict.price, Decimal("500.0"))
        self.assertEqual(verdict.order, self.order)
        self.assertEqual(verdict.share, self.share)
        loader.assert_called_once_with(1001)

    def test_finished_contract_is_credited(self):
        verdict, _loader = self._classify(self._contract(status="finished"))

        self.assertEqual(verdict.outcome, Outcome.CREDIT)
        self.assertEqual(verdict.quantity, 5)

    def test_other_items_in_the_contract_do_not_matter(self):
        items = self._items() + self._items(quantity=100, type_id=999)

        verdict, _loader = self._classify(items=items)

        self.assertEqual(verdict.outcome, Outcome.PENDING)
        self.assertEqual(verdict.quantity, 5)

    def test_quantities_of_the_item_are_added_up(self):
        items = self._items(quantity=3) + self._items(quantity=2)

        verdict, _loader = self._classify(items=items)

        self.assertEqual(verdict.quantity, 5)

    def test_prices_within_the_tolerance_are_accepted(self):
        accepted, _loader = self._classify(self._contract(price=500.01))
        refused, _loader = self._classify(self._contract(price=500.02))

        self.assertEqual(accepted.outcome, Outcome.PENDING)
        self.assertEqual(refused.outcome, Outcome.INVALID)

    def test_own_waiting_record_does_not_count_against_itself(self):
        self._record(ContractRecord.State.OUTSTANDING, quantity=5)

        verdict, _loader = self._classify()

        self.assertEqual(verdict.outcome, Outcome.PENDING)

    def test_a_credited_contract_is_left_alone(self):
        self._record(ContractRecord.State.CREDITED)

        verdict, loader = self._classify(self._contract(status="finished"))

        self.assertEqual(verdict.outcome, Outcome.IGNORE)
        loader.assert_not_called()


class TestForeignContracts(MatchingTestCase):
    """Contracts that are not our business"""

    def test_other_types_and_assignees_are_ignored(self):
        for overrides in ({"type": "courier"}, {"assignee_id": 12345}):
            with self.subTest(overrides=overrides):
                verdict, loader = self._classify(self._contract(**overrides))

                self.assertEqual(verdict.outcome, Outcome.IGNORE)
                loader.assert_not_called()

    def test_unknown_issuer_without_a_number_is_ignored(self):
        verdict, loader = self._classify(
            self._contract(issuer_id=999, title="HLOP TYPHOON")
        )

        self.assertEqual(verdict.outcome, Outcome.IGNORE)
        loader.assert_not_called()

    def test_unknown_issuer_with_an_unknown_number_is_ignored(self):
        verdict, _loader = self._classify(
            self._contract(issuer_id=999, title="N20990101-1")
        )

        self.assertEqual(verdict.outcome, Outcome.IGNORE)

    def test_cancelled_contracts_we_never_saw_are_ignored(self):
        verdict, loader = self._classify(self._contract(status="deleted"))

        self.assertEqual(verdict.outcome, Outcome.IGNORE)
        loader.assert_not_called()


class TestInvalidContracts(MatchingTestCase):
    """Contracts that look like deliveries but cannot be counted"""

    def _assert_invalid(self, verdict, loader, called=False):
        self.assertEqual(verdict.outcome, Outcome.INVALID)
        self.assertTrue(verdict.reason)
        self.assertEqual(loader.called, called)

    def test_builder_forgot_the_number(self):
        verdict, loader = self._classify(self._contract(title=""))

        self._assert_invalid(verdict, loader)
        self.assertIn("order number", verdict.reason)

    def test_two_order_numbers(self):
        verdict, loader = self._classify(
            self._contract(title="N20261027-1 N20261027-2")
        )

        self._assert_invalid(verdict, loader)

    def test_unknown_order_number_from_a_known_builder(self):
        verdict, loader = self._classify(self._contract(title="N20990101-1"))

        self._assert_invalid(verdict, loader)

    def test_issuer_is_not_on_an_auth_account(self):
        verdict, loader = self._classify(self._contract(issuer_id=999))

        self._assert_invalid(verdict, loader)
        self.assertEqual(verdict.order, self.order)

    def test_issuer_has_not_taken_the_order(self):
        other = make_user("other", "builder_access")
        contract = self._contract(issuer_id=other.profile.main_character.character_id)

        verdict, loader = self._classify(contract)

        self._assert_invalid(verdict, loader)

    def test_wrong_item(self):
        verdict, loader = self._classify(items=self._items(type_id=999))

        self._assert_invalid(verdict, loader, called=True)

    def test_item_that_is_only_requested_does_not_count(self):
        verdict, loader = self._classify(items=self._items(included=False))

        self._assert_invalid(verdict, loader, called=True)

    def test_wrong_price(self):
        verdict, loader = self._classify(self._contract(price=499.0))

        self._assert_invalid(verdict, loader, called=True)
        self.assertEqual(verdict.quantity, 5)

    def test_more_than_is_left_to_deliver(self):
        verdict, loader = self._classify(
            self._contract(price=600.0), items=self._items(quantity=6)
        )

        self._assert_invalid(verdict, loader, called=True)

    def test_waiting_contracts_reduce_what_is_left(self):
        self._record(ContractRecord.State.OUTSTANDING, quantity=3, contract_id=2002)

        too_many, _loader = self._classify(
            self._contract(price=300.0), items=self._items(quantity=3)
        )
        fits, _loader = self._classify(
            self._contract(price=200.0), items=self._items(quantity=2)
        )

        self.assertEqual(too_many.outcome, Outcome.INVALID)
        self.assertEqual(fits.outcome, Outcome.PENDING)

    def test_credited_items_reduce_what_is_left(self):
        OrderAssignment.objects.filter(pk=self.share.pk).update(credited=3)

        verdict, _loader = self._classify()  # 5 items, only 2 are left

        self.assertEqual(verdict.outcome, Outcome.INVALID)


class TestEndedContracts(MatchingTestCase):
    """Contracts that ended without success"""

    def test_known_contracts_that_ended_are_closed(self):
        for status in ("deleted", "rejected", "failed", "cancelled", "reversed"):
            with self.subTest(status=status):
                ContractRecord.objects.all().delete()
                self._record(ContractRecord.State.OUTSTANDING)

                verdict, loader = self._classify(self._contract(status=status))

                self.assertEqual(verdict.outcome, Outcome.CLOSED)
                self.assertEqual(verdict.quantity, 5)
                loader.assert_not_called()

    def test_expired_outstanding_contracts_are_closed(self):
        self._record(ContractRecord.State.OUTSTANDING)

        verdict, _loader = self._classify(
            self._contract(date_expired="2020-01-01T00:00:00Z")
        )

        self.assertEqual(verdict.outcome, Outcome.CLOSED)

    def test_a_deleted_invalid_contract_is_closed_too(self):
        self._record(ContractRecord.State.INVALID)

        verdict, _loader = self._classify(self._contract(status="deleted"))

        self.assertEqual(verdict.outcome, Outcome.CLOSED)
