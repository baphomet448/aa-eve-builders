"""The page "Contracts on review", and the cost to buy out on the list of orders"""

# Standard Library
import re
from datetime import timedelta
from decimal import Decimal

# Django
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

# AA EVE Builders
from evebuilders.messages import display_name
from evebuilders.models import ContractRecord, Order, OrderAssignment
from evebuilders.review import PAGE_SIZE
from evebuilders.statistics import buyout_cost
from evebuilders.templatetags.evebuilders_extras import isk
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES, make_user

User = get_user_model()


@override_settings(STORAGES=TEST_STORAGES)
class ReviewTestCase(ViewsTestCase):
    """
    self.manager is an admin, self.cr_officer a manager (the builder of the
    fixtures with the permission of a manager), self.cr_plain a builder and nothing
    else. The contracts are made by self.other, a builder.
    """

    def setUp(self):
        self.builder.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="evebuilders", codename="manager_access"
            )
        )
        self.cr_officer = User.objects.get(pk=self.builder.pk)
        self.cr_plain = make_user("plain", "builder_access")
        self._take(self.other, 20)
        self.cr_share = OrderAssignment.objects.get(
            order=self.order, builder=self.other
        )
        self.cr_next_id = 1

    def cr_contract(
        self, quantity, price, *, state=None, issued=None, order=None, share=None
    ):
        """A contract of a builder for an order"""

        record = ContractRecord.objects.create(
            contract_id=self.cr_next_id,
            order=order or self.order,
            assignment=share or self.cr_share,
            issuer_character_id=1,
            quantity=quantity,
            price=Decimal(price),
            state=state or ContractRecord.State.OUTSTANDING,
            issued_at=issued or timezone.now(),
        )
        self.cr_next_id += 1

        return record

    def cr_middle_share(self):
        """A share of self.builder (the officer) in the middle order"""

        self._take(self.builder, 10, order=self.middle)

        return OrderAssignment.objects.get(order=self.middle, builder=self.builder)

    def cr_get(self, user, **params):
        self.client.force_login(user)

        return self.client.get(reverse("evebuilders:contracts_review"), params)

    def cr_orders(self, user):
        self.client.force_login(user)

        return self.client.get(reverse("evebuilders:orders"))

    @staticmethod
    def cr_ids(response) -> list[int]:
        return [row["record"].contract_id for row in response.context["result"].rows]


class TestTheReviewPage(ReviewTestCase):
    """What the page shows"""

    def test_only_managers_get_in(self):
        self.assertEqual(self.cr_get(self.cr_plain).status_code, 302)
        self.assertEqual(self.cr_get(self.cr_officer).status_code, 200)
        self.assertEqual(self.cr_get(self.manager).status_code, 200)

    def test_a_contract_is_described(self):
        Order.objects.filter(pk=self.order.pk).update(destination="Jita 4-4")
        self.cr_contract(5, "5000000")

        response = self.cr_get(self.manager)

        self.assertContains(response, self.order.number)
        self.assertContains(response, self.order.eve_type.name)
        self.assertContains(response, isk(self.order.unit_price))
        self.assertContains(response, '<td class="text-end">5</td>')
        self.assertContains(response, "Jita 4-4")
        self.assertContains(response, display_name(self.other))

    def test_the_titles(self):
        response = self.cr_get(self.manager)

        self.assertContains(response, "Contracts on review")
        self.assertContains(response, "Total cost of the contracts to buy out")

    def test_only_the_contracts_that_wait_are_listed(self):
        self.cr_contract(5, "5000000")
        self.cr_contract(3, "3000000", state=ContractRecord.State.CREDITED)

        self.assertEqual(self.cr_ids(self.cr_get(self.manager)), [1])

    def test_the_oldest_contract_is_first(self):
        now = timezone.now()
        self.cr_contract(1, "1000000", issued=now)
        self.cr_contract(1, "1000000", issued=now - timedelta(days=2))
        self.cr_contract(1, "1000000", issued=now - timedelta(days=1))

        self.assertEqual(self.cr_ids(self.cr_get(self.manager)), [2, 3, 1])

    def test_without_contracts_it_says_so(self):
        response = self.cr_get(self.manager)

        self.assertContains(response, "No contracts are waiting for acceptance.")
        self.assertContains(response, "0 ISK")


class TestTheTotal(ReviewTestCase):
    """The cost of the contracts to buy out"""

    def test_the_total_is_the_sum_of_the_contracts_that_wait(self):
        self.cr_contract(5, "5000000")
        self.cr_contract(3, "3000000")
        self.cr_contract(1, "1000000", state=ContractRecord.State.CREDITED)

        response = self.cr_get(self.manager)

        self.assertContains(response, "8,000,000 ISK")
        self.assertNotContains(response, "9,000,000 ISK")

    def test_the_total_follows_the_filter(self):
        share = self.cr_middle_share()
        self.cr_contract(5, "5000000")
        self.cr_contract(3, "3000000", order=self.middle, share=share)

        response = self.cr_get(self.manager, q=self.middle.number)

        self.assertContains(response, "3,000,000 ISK")
        self.assertNotContains(response, "8,000,000 ISK")

    def test_the_total_counts_every_page_not_only_the_one_shown(self):
        ContractRecord.objects.bulk_create(
            [
                ContractRecord(
                    contract_id=1000 + number,
                    order=self.order,
                    assignment=self.cr_share,
                    issuer_character_id=1,
                    quantity=1,
                    price=Decimal("1000"),
                    state=ContractRecord.State.OUTSTANDING,
                    issued_at=timezone.now(),
                )
                for number in range(PAGE_SIZE + 10)
            ]
        )

        response = self.cr_get(self.manager)

        self.assertEqual(len(response.context["result"].rows), PAGE_SIZE)
        self.assertContains(response, f"{(PAGE_SIZE + 10) * 1000:,} ISK")


class TestFilterAndSorting(ReviewTestCase):
    """The filter, the sorting and the pages"""

    def setUp(self):
        super().setUp()
        Order.objects.filter(pk=self.order.pk).update(destination="Jita 4-4")
        Order.objects.filter(pk=self.middle.pk).update(destination="Amarr VIII")
        middle_share = self.cr_middle_share()
        self.cr_contract(5, "5000000")
        self.cr_contract(8, "8000000", order=self.middle, share=middle_share)

    def test_by_the_number_of_the_order(self):
        response = self.cr_get(self.manager, q=self.middle.number)

        self.assertEqual(self.cr_ids(response), [2])

    def test_by_the_destination(self):
        self.assertEqual(self.cr_ids(self.cr_get(self.manager, q="amarr")), [2])

    def test_by_the_builder(self):
        name = display_name(self.other).split()[0]

        self.assertEqual(self.cr_ids(self.cr_get(self.manager, q=name)), [1])

    def test_by_the_item(self):
        response = self.cr_get(self.manager, q="punisher")

        self.assertEqual(sorted(self.cr_ids(response)), [1, 2])

    def test_nothing_that_matches_is_said_so(self):
        response = self.cr_get(self.manager, q="no such thing")

        self.assertContains(response, "Nothing matches the filter.")
        self.assertContains(response, "0 ISK")

    def test_by_the_quantity(self):
        self.assertEqual(
            self.cr_ids(self.cr_get(self.manager, sort="quantity", dir="desc")),
            [2, 1],
        )
        self.assertEqual(
            self.cr_ids(self.cr_get(self.manager, sort="quantity")), [1, 2]
        )

    def test_by_the_destination_column(self):
        self.assertEqual(self.cr_ids(self.cr_get(self.manager, sort="place")), [2, 1])

    def test_an_unknown_sorting_is_ignored(self):
        self.assertEqual(self.cr_ids(self.cr_get(self.manager, sort="nope")), [1, 2])

    def test_the_title_of_the_sorted_column_turns_the_sorting_around(self):
        result = self.cr_get(self.manager, sort="quantity").context["result"]

        link = result.sort_links["quantity"]
        self.assertEqual(link["arrow"], " ▲")
        self.assertIn("dir=desc", link["url"])
        self.assertEqual(result.sort_links["order"]["arrow"], "")

    def test_the_pages_keep_the_filter(self):
        ContractRecord.objects.bulk_create(
            [
                ContractRecord(
                    contract_id=1000 + number,
                    order=self.order,
                    assignment=self.cr_share,
                    issuer_character_id=1,
                    quantity=1,
                    price=Decimal("1000"),
                    state=ContractRecord.State.OUTSTANDING,
                    issued_at=timezone.now(),
                )
                for number in range(PAGE_SIZE + 5)
            ]
        )

        result = self.cr_get(self.manager, q="jita", page=1).context["result"]

        self.assertEqual(len(result.rows), PAGE_SIZE)
        self.assertEqual(result.previous_url, "")
        self.assertIn("q=jita", result.next_url)
        self.assertIn("page=2", result.next_url)

        second = self.cr_get(self.manager, q="jita", page=2).context["result"]
        self.assertEqual(second.page.number, 2)
        self.assertEqual(second.next_url, "")


class TestBuyoutOnTheOrderList(ReviewTestCase):
    """The cost to buy out the active orders next to the filters"""

    def test_a_manager_sees_the_cost(self):
        response = self.cr_orders(self.cr_officer)

        self.assertContains(response, "Buyout cost of the active orders")
        self.assertContains(response, f"{isk(buyout_cost())} ISK")

    def test_an_admin_sees_the_cost(self):
        self.assertContains(
            self.cr_orders(self.manager), "Buyout cost of the active orders"
        )

    def test_a_builder_does_not(self):
        response = self.cr_orders(self.cr_plain)

        self.assertNotContains(response, "Buyout cost of the active orders")


class TestTheMenu(ReviewTestCase):
    """The link to the page"""

    def test_the_link_is_for_managers(self):
        link = f'href="{reverse("evebuilders:contracts_review")}"'

        self.assertContains(self.cr_orders(self.cr_officer), link)
        self.assertContains(self.cr_orders(self.manager), link)
        self.assertNotContains(self.cr_orders(self.cr_plain), link)

    def test_the_link_is_between_the_corporate_orders_and_my_orders(self):
        content = self.cr_orders(self.manager).content.decode()

        corporate = content.index(f'href="{reverse("evebuilders:orders")}"')
        review = content.index(f'href="{reverse("evebuilders:contracts_review")}"')
        mine = content.index(f'href="{reverse("evebuilders:my_orders")}"')

        self.assertLess(corporate, review)
        self.assertLess(review, mine)

    @staticmethod
    def cr_classes(response, url_name: str) -> str:
        """The classes of the link of the top bar that goes to a page"""

        url = reverse(url_name)
        match = re.search(
            rf'<a class="nav-link ([^"]*)"\s+href="{re.escape(url)}"',
            response.content.decode(),
        )

        assert match is not None, f"No link to {url} in the top bar"

        return match.group(1)

    def test_the_link_is_marked_on_its_own_page(self):
        response = self.cr_get(self.manager)

        self.assertIn(
            "active", self.cr_classes(response, "evebuilders:contracts_review")
        )
        self.assertNotIn("active", self.cr_classes(response, "evebuilders:orders"))
        self.assertNotIn("active", self.cr_classes(response, "evebuilders:my_orders"))

    def test_the_link_is_not_marked_on_the_other_pages(self):
        response = self.cr_orders(self.manager)

        self.assertNotIn(
            "active", self.cr_classes(response, "evebuilders:contracts_review")
        )
        self.assertIn("active", self.cr_classes(response, "evebuilders:orders"))
