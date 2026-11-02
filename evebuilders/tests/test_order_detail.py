"""The order details page and the manager forms"""

# Django
from django.contrib.messages import constants, get_messages
from django.test import Client, override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.messages import display_name
from evebuilders.models import ContractRecord, Order, OrderAssignment, OrderEvent
from evebuilders.order_detail import contract_choices
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES


class DetailTestCase(ViewsTestCase):
    """A builder with a share of 400 of an order of 1000"""

    def setUp(self):
        self.share = self._take(self.builder, 400)

    def _url(self, name, order=None):
        return reverse(f"evebuilders:{name}", args=[(order or self.order).pk])

    def _record(self, state, quantity=0, contract_id=1001, issuer=None, **extra):
        issuer = issuer or self.builder

        return ContractRecord.objects.create(
            contract_id=contract_id,
            issuer_character_id=issuer.profile.main_character.character_id,
            quantity=quantity,
            state=state,
            **extra,
        )

    def _post(self, name, data, user=None):
        client = Client()  # fresh client: no messages left over from before
        client.force_login(user or self.manager)

        return client.post(self._url(name), data)

    @staticmethod
    def _levels(response):
        return [m.level for m in get_messages(response.wsgi_request)]


class TestContractChoices(DetailTestCase):
    """contract_choices"""

    def test_the_contracts_a_manager_may_close(self):
        mine_waiting = self._record(
            ContractRecord.State.OUTSTANDING,
            quantity=5,
            contract_id=1,
            order=self.order,
            assignment=self.share,
        )
        unlinked = self._record(ContractRecord.State.INVALID, contract_id=2)
        self._record(ContractRecord.State.INVALID, contract_id=3, issuer=self.other)
        self._record(
            ContractRecord.State.CREDITED,
            contract_id=4,
            order=self.order,
            assignment=self.share,
        )

        choices = contract_choices(self.share)

        self.assertEqual({c.pk for c in choices}, {mine_waiting.pk, unlinked.pk})


@override_settings(STORAGES=TEST_STORAGES)
class TestOrderDetailPage(DetailTestCase):
    """The page"""

    def test_anonymous_and_builders_are_sent_away(self):
        url = self._url("order_detail")

        self.assertEqual(self.client.get(url).status_code, 302)

        self.client.force_login(self.builder)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_an_unknown_or_private_order_is_not_found(self):
        self.client.force_login(self.manager)
        Order.objects.filter(pk=self.middle.pk).update(kind=Order.Kind.PRIVATE)

        unknown = self.client.get(reverse("evebuilders:order_detail", args=[999999]))
        private = self.client.get(self._url("order_detail", self.middle))

        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(private.status_code, 404)

    def test_it_shows_the_order_the_builders_and_the_history(self):
        self.client.force_login(self.manager)

        response = self.client.get(self._url("order_detail"))

        self.assertContains(response, self.order.number)
        self.assertContains(response, "Punisher")
        self.assertContains(response, display_name(self.builder))
        self.assertContains(response, "Took 400")
        self.assertContains(response, self._url("release"))
        self.assertContains(response, self._url("credit"))

    def test_it_shows_the_contracts_of_the_order(self):
        self._record(
            ContractRecord.State.INVALID,
            quantity=3,
            order=self.order,
            assignment=self.share,
            title="Wrong contract title",
            reason="The price must be 100.00 ISK for 3 items.",
        )
        self.client.force_login(self.manager)

        response = self.client.get(self._url("order_detail"))

        self.assertContains(response, "Wrong contract title")
        self.assertContains(response, "The price must be 100.00 ISK for 3 items.")

    def test_the_credit_form_offers_the_builders_problem_contracts_only(self):
        self._record(ContractRecord.State.INVALID, contract_id=555)
        self._record(ContractRecord.State.INVALID, contract_id=556, issuer=self.other)
        self.client.force_login(self.manager)

        response = self.client.get(self._url("order_detail"))

        self.assertContains(response, 'value="555"')
        self.assertNotContains(response, 'value="556"')

    def test_the_order_list_links_to_it_for_managers_only(self):
        link = f'href="{self._url("order_detail")}"'

        self.client.force_login(self.manager)
        manager_page = self.client.get(reverse("evebuilders:orders"))
        self.client.force_login(self.builder)
        builder_page = self.client.get(reverse("evebuilders:orders"))

        self.assertContains(manager_page, link)
        self.assertNotContains(builder_page, link)


class TestReleaseView(DetailTestCase):
    """The Release form"""

    def test_a_manager_releases_a_share(self):
        response = self._post("release", {"share": self.share.pk, "quantity": "150"})

        self.assertRedirects(
            response, self._url("order_detail"), fetch_redirect_response=False
        )
        self.share.refresh_from_db()
        self.assertEqual(self.share.taken, 250)
        self.assertEqual(self._levels(response), [constants.SUCCESS])

    def test_an_empty_quantity_releases_everything_possible(self):
        self._post("release", {"share": self.share.pk, "quantity": ""})

        self.share.refresh_from_db()
        self.assertEqual(self.share.taken, 0)

    def test_nothing_to_release_is_an_error(self):
        ContractRecord.objects.create(
            contract_id=1,
            order=self.order,
            assignment=self.share,
            issuer_character_id=1,
            quantity=400,
            state=ContractRecord.State.OUTSTANDING,
        )

        response = self._post("release", {"share": self.share.pk, "quantity": ""})

        self.assertEqual(self._levels(response), [constants.ERROR])
        self.share.refresh_from_db()
        self.assertEqual(self.share.taken, 400)

    def test_bad_numbers_are_an_error(self):
        for data in (
            {"share": "abc"},
            {"share": "", "quantity": "5"},
            {"share": self.share.pk, "quantity": "x"},
        ):
            with self.subTest(data=data):
                response = self._post("release", data)

                self.assertEqual(self._levels(response), [constants.ERROR])

        self.share.refresh_from_db()
        self.assertEqual(self.share.taken, 400)

    def test_builders_cannot_release_and_get_is_not_allowed(self):
        response = self._post("release", {"share": self.share.pk}, user=self.builder)

        self.assertEqual(response.status_code, 302)
        self.share.refresh_from_db()
        self.assertEqual(self.share.taken, 400)

        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(self._url("release")).status_code, 405)


class TestCreditView(DetailTestCase):
    """The Credit manually form"""

    def test_a_manager_credits_by_hand(self):
        response = self._post(
            "credit",
            {"share": self.share.pk, "quantity": "150", "comment": "in person"},
        )

        self.assertRedirects(
            response, self._url("order_detail"), fetch_redirect_response=False
        )
        self.share.refresh_from_db()
        self.assertEqual(self.share.credited, 150)
        self.assertEqual(self._levels(response), [constants.SUCCESS])
        self.assertIn(
            "in person",
            OrderEvent.objects.get(kind=OrderEvent.Kind.MANUAL_CREDIT).description,
        )

    def test_crediting_closes_a_contract_without_an_order(self):
        record = self._record(ContractRecord.State.INVALID, contract_id=555)

        self._post(
            "credit", {"share": self.share.pk, "quantity": "100", "contract": "555"}
        )

        record.refresh_from_db()
        self.assertEqual(record.state, ContractRecord.State.CREDITED)
        self.assertEqual(record.assignment, self.share)

    def test_more_than_is_left_is_an_error(self):
        response = self._post("credit", {"share": self.share.pk, "quantity": "401"})

        self.assertEqual(self._levels(response), [constants.ERROR])
        self.share.refresh_from_db()
        self.assertEqual(self.share.credited, 0)

    def test_bad_numbers_are_an_error(self):
        for data in (
            {"share": self.share.pk, "quantity": ""},
            {"share": self.share.pk, "quantity": "x"},
            {"share": self.share.pk, "quantity": "5", "contract": "zz"},
        ):
            with self.subTest(data=data):
                response = self._post("credit", data)

                self.assertEqual(self._levels(response), [constants.ERROR])

        self.share.refresh_from_db()
        self.assertEqual(self.share.credited, 0)

    def test_builders_cannot_credit(self):
        response = self._post(
            "credit", {"share": self.share.pk, "quantity": "10"}, user=self.builder
        )

        self.assertEqual(response.status_code, 302)
        self.share.refresh_from_db()
        self.assertEqual(self.share.credited, 0)

    def test_the_other_builders_share_of_the_same_order_is_not_affected(self):
        other_share = self._take(self.other, 100)

        self._post("credit", {"share": self.share.pk, "quantity": "50"})

        other_share.refresh_from_db()
        self.assertEqual(other_share.credited, 0)
        self.assertEqual(OrderAssignment.objects.get(pk=self.share.pk).credited, 50)
