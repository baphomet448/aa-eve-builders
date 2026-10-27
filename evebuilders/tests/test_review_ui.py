"""Review status, problem contracts and the On review column"""

# Django
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

# AA EVE Builders
from evebuilders.models import ContractRecord, ContractSource, OrderAssignment
from evebuilders.orders import my_shares, problem_contracts, visible_orders
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES


class ReviewTestCase(ViewsTestCase):
    """A builder with a share, and helpers for contract records"""

    def _contract(self, share, quantity, state, contract_id, issuer=None, **extra):
        issuer = issuer or self.builder

        return ContractRecord.objects.create(
            contract_id=contract_id,
            order=self.order,
            assignment=share,
            issuer_character_id=issuer.profile.main_character.character_id,
            quantity=quantity,
            state=state,
            **extra,
        )


class TestShareStatus(ReviewTestCase):
    """The status badge of a share"""

    def _status(self):
        return my_shares(self.builder)[0]["status"]

    def test_in_progress_until_something_waits(self):
        self._take(self.builder, 400)

        self.assertEqual(self._status(), "IN_PROGRESS")

    def test_under_review_while_a_contract_waits(self):
        share = self._take(self.builder, 400)
        self._contract(share, 100, ContractRecord.State.OUTSTANDING, 1001)

        self.assertEqual(self._status(), "UNDER_REVIEW")

    def test_done_when_everything_is_credited(self):
        share = self._take(self.builder, 400)
        OrderAssignment.objects.filter(pk=share.pk).update(credited=400)

        self.assertEqual(self._status(), "DONE")

    def test_a_closed_contract_does_not_count_as_waiting(self):
        share = self._take(self.builder, 400)
        self._contract(share, 100, ContractRecord.State.CLOSED, 1001)

        self.assertEqual(self._status(), "IN_PROGRESS")


class TestProblemContracts(ReviewTestCase):
    """problem_contracts"""

    def test_only_own_invalid_contracts_are_listed(self):
        share = self._take(self.builder, 400)
        mine = self._contract(share, 1, ContractRecord.State.INVALID, 1001)
        self._contract(share, 1, ContractRecord.State.INVALID, 1002, issuer=self.other)
        self._contract(share, 1, ContractRecord.State.OUTSTANDING, 1003)
        self._contract(share, 1, ContractRecord.State.CLOSED, 1004)

        self.assertEqual(list(problem_contracts(self.builder)), [mine])


class TestPendingColumn(ReviewTestCase):
    """The pending number of visible_orders"""

    def test_pending_sums_waiting_contracts_and_leaves_other_sums_alone(self):
        share = self._take(self.builder, 300)
        other_share = self._take(self.other, 200)
        OrderAssignment.objects.filter(pk=share.pk).update(credited=100)
        OrderAssignment.objects.filter(pk=other_share.pk).update(credited=50)
        self._contract(share, 100, ContractRecord.State.OUTSTANDING, 1001)
        self._contract(share, 50, ContractRecord.State.OUTSTANDING, 1002)
        self._contract(share, 70, ContractRecord.State.CLOSED, 1003)
        self._contract(share, 30, ContractRecord.State.INVALID, 1004)

        order = visible_orders(self.manager).get(pk=self.order.pk)

        self.assertEqual(order.pending, 150)
        self.assertEqual(order.taken, 500)
        self.assertEqual(order.credited, 150)
        self.assertEqual(order.free, 500)

    def test_orders_without_contracts_have_nothing_pending(self):
        order = visible_orders(self.manager).get(pk=self.order.pk)

        self.assertEqual(order.pending, 0)


@override_settings(STORAGES=TEST_STORAGES)
class TestPages(ReviewTestCase):
    """What the pages show"""

    def test_my_orders_shows_the_review_badge(self):
        share = self._take(self.builder, 400)
        self._contract(share, 100, ContractRecord.State.OUTSTANDING, 1001)
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:my_orders"))

        self.assertContains(response, "Under review")

    def test_my_orders_lists_the_problem_contracts_of_the_user_only(self):
        share = self._take(self.builder, 400)
        self._contract(
            share,
            1,
            ContractRecord.State.INVALID,
            1001,
            title="Wrong contract",
            reason="The price must be 100.00 ISK for 1 items.",
            issued_at=timezone.now(),
        )

        self.client.force_login(self.builder)
        mine = self.client.get(reverse("evebuilders:my_orders"))
        self.client.force_login(self.other)
        theirs = self.client.get(reverse("evebuilders:my_orders"))

        self.assertContains(mine, "Contracts that could not be counted")
        self.assertContains(mine, "Wrong contract")
        self.assertContains(mine, "The price must be 100.00 ISK for 1 items.")
        self.assertNotContains(theirs, "Wrong contract")

    def test_my_orders_says_when_contracts_were_last_checked(self):
        self.client.force_login(self.builder)

        without_source = self.client.get(reverse("evebuilders:my_orders"))
        ContractSource.objects.create(
            corporation_id=98000001,
            corporation_name="Test Corp",
            last_success_at=timezone.now(),
        )
        with_source = self.client.get(reverse("evebuilders:my_orders"))

        self.assertContains(without_source, "ESI is not connected yet")
        self.assertContains(with_source, "Contracts were last checked")

    def test_the_order_list_has_the_on_review_column(self):
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:orders"))

        self.assertContains(response, "On review")