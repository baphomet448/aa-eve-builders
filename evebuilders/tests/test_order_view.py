"""Order form view tests"""

# Standard Library
from datetime import timedelta

# Django
from django.contrib.messages import constants, get_messages
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

# EVE Universe
from eveuniverse.models import EveCategory, EveGroup, EveType

# AA EVE Builders
from evebuilders.models import Order, OrderEvent
from evebuilders.tests.test_views import TEST_STORAGES, make_user


@override_settings(STORAGES=TEST_STORAGES)
class TestNewOrderView(TestCase):
    """The order form page"""

    @classmethod
    def setUpTestData(cls) -> None:
        category = EveCategory.objects.create(id=6, name="Ship", published=True)
        group = EveGroup.objects.create(
            id=25, name="Frigate", eve_category=category, published=True
        )
        EveType.objects.create(id=597, name="Punisher", eve_group=group, published=True)
        cls.manager = make_user("manager", "manage_access")
        cls.builder = make_user("builder", "builder_access")

    def _post_data(self, **overrides):
        data = {
            "item_text": "Punisher",
            "eve_type_id": "597",
            "quantity": "500",
            "unit_price": "1000000.00",
            "priority": "MEDIUM",
            "due_date": (timezone.localdate() + timedelta(days=7)).isoformat(),
            "access_level": "1",
            "destination": "Jita",
            "note": "",
        }
        data.update(overrides)

        return data

    def test_anonymous_and_builders_are_sent_away(self):
        url = reverse("evebuilders:new_order")

        self.assertEqual(self.client.get(url).status_code, 302)

        self.client.force_login(self.builder)
        self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(self.client.post(url, self._post_data()).status_code, 302)
        self.assertFalse(Order.objects.exists())

    def test_manager_sees_the_form(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:new_order"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "New corporate order")
        self.assertContains(response, reverse("evebuilders:item_search"))
        expected = timezone.localdate() + timedelta(days=7)
        self.assertEqual(response.context["form"].initial["due_date"], expected)

    def test_valid_post_creates_the_order(self):
        self.client.force_login(self.manager)

        response = self.client.post(reverse("evebuilders:new_order"), self._post_data())

        self.assertRedirects(
            response, reverse("evebuilders:index"), fetch_redirect_response=False
        )
        order = Order.objects.get()
        self.assertTrue(order.number.startswith("N"))
        self.assertEqual(order.quantity, 500)
        self.assertEqual(order.destination, "Jita")
        self.assertEqual(order.created_by, self.manager)
        self.assertEqual(
            OrderEvent.objects.get(order=order).kind, OrderEvent.Kind.CREATED
        )
        levels = [m.level for m in get_messages(response.wsgi_request)]
        self.assertEqual(levels, [constants.SUCCESS])

    def test_invalid_post_shows_errors_and_creates_nothing(self):
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("evebuilders:new_order"), self._post_data(quantity="0")
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("quantity", response.context["form"].errors)
        self.assertFalse(Order.objects.exists())

    def test_item_outside_the_catalog_is_refused(self):
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("evebuilders:new_order"), self._post_data(eve_type_id="424242")
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("eve_type_id", response.context["form"].errors)
        self.assertFalse(Order.objects.exists())

    def test_tab_is_only_shown_to_managers(self):
        url = reverse("evebuilders:new_order")

        self.client.force_login(self.manager)
        manager_page = self.client.get(reverse("evebuilders:index"))
        self.client.force_login(self.builder)
        builder_page = self.client.get(reverse("evebuilders:index"))

        self.assertContains(manager_page, url)
        self.assertNotContains(builder_page, url)