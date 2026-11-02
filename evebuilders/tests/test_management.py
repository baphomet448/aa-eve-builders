"""The Management page"""

# Django
from django.test import override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.levels import set_builder_level
from evebuilders.messages import display_name
from evebuilders.models import ContractRecord, Order
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES


@override_settings(STORAGES=TEST_STORAGES)
class TestManagementPage(ViewsTestCase):
    """What needs a manager's attention"""

    def setUp(self):
        self.share = self._take(self.builder, 400)

    def _record(self, state, contract_id, issuer=None, **extra):
        issuer = issuer or self.builder

        return ContractRecord.objects.create(
            contract_id=contract_id,
            issuer_character_id=issuer.profile.main_character.character_id,
            state=state,
            **extra,
        )

    def _page(self):
        self.client.force_login(self.manager)

        return self.client.get(reverse("evebuilders:management"))

    @staticmethod
    def _detail(order):
        return f'href="{reverse("evebuilders:order_detail", args=[order.pk])}"'

    def test_anonymous_and_builders_are_sent_away(self):
        url = reverse("evebuilders:management")

        self.assertEqual(self.client.get(url).status_code, 302)

        self.client.force_login(self.builder)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_a_problem_contract_without_an_order_points_to_the_builders_orders(self):
        another = self._order()
        self._take(self.builder, 10, order=another)
        self._record(
            ContractRecord.State.INVALID,
            555,
            title="No number here",
            reason="The contract title has no order number.",
        )

        response = self._page()

        problems = response.content.decode().split("Waiting for acceptance")[0]
        self.assertIn("No number here", problems)
        self.assertIn("The contract title has no order number.", problems)
        self.assertIn(display_name(self.builder), problems)
        self.assertIn(self._detail(self.order), problems)
        self.assertIn(self._detail(another), problems)

    def test_a_problem_contract_with_an_order_points_to_that_order_only(self):
        another = self._order()
        self._take(self.builder, 10, order=another)
        self._record(
            ContractRecord.State.INVALID,
            556,
            order=another,
            title="Wrong price",
            reason="The price must be 100.00 ISK for 1 items.",
        )

        response = self._page()

        # Only the table of problem contracts: the activity list links to orders too
        problems = response.content.decode().split("Waiting for acceptance")[0]
        self.assertIn("Wrong price", problems)
        self.assertIn(self._detail(another), problems)
        self.assertNotIn(self._detail(self.order), problems)

    def test_only_invalid_contracts_are_problems(self):
        self._record(
            ContractRecord.State.CREDITED, 1, order=self.order, title="Credited one"
        )
        self._record(
            ContractRecord.State.CLOSED, 2, order=self.order, title="Closed one"
        )

        response = self._page()

        self.assertNotContains(response, "Credited one")
        self.assertNotContains(response, "Closed one")
        self.assertContains(response, "Nothing needs attention.")

    def test_waiting_contracts_are_listed(self):
        self._record(
            ContractRecord.State.OUTSTANDING,
            777,
            order=self.order,
            assignment=self.share,
            quantity=5,
            title="Waiting contract",
        )

        response = self._page()

        self.assertContains(response, "777")
        self.assertContains(response, self._detail(self.order))

    def test_the_latest_activity_includes_events_that_belong_to_no_order(self):
        set_builder_level(
            actor=self.manager, user=self.builder, level=Order.AccessLevel.MIDDLE
        )

        response = self._page()

        self.assertContains(response, "Level of")
        self.assertContains(response, "Took 400")

    def test_the_menu_button_is_for_managers_only(self):
        url = f'href="{reverse("evebuilders:management")}"'

        self.client.force_login(self.manager)
        manager_page = self.client.get(reverse("evebuilders:orders"))
        self.client.force_login(self.builder)
        builder_page = self.client.get(reverse("evebuilders:orders"))

        self.assertContains(manager_page, url)
        self.assertNotContains(builder_page, url)
