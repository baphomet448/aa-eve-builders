"""Form tests"""

# Standard Library
from datetime import timedelta

# Django
from django.test import TestCase
from django.utils import timezone

# EVE Universe
from eveuniverse.models import EveCategory, EveGroup, EveType

# AA EVE Builders
from evebuilders.forms import OrderForm
from evebuilders.models import Order


class TestOrderForm(TestCase):
    """OrderForm validation"""

    @classmethod
    def setUpTestData(cls) -> None:
        ship_category = EveCategory.objects.create(id=6, name="Ship", published=True)
        ship_group = EveGroup.objects.create(
            id=25, name="Frigate", eve_category=ship_category, published=True
        )
        cls.eve_type = EveType.objects.create(
            id=597, name="Punisher", eve_group=ship_group, published=True
        )
        other_category = EveCategory.objects.create(id=99, name="Other", published=True)
        other_group = EveGroup.objects.create(
            id=999, name="Other group", eve_category=other_category, published=True
        )
        EveType.objects.create(
            id=1, name="Not orderable", eve_group=other_group, published=True
        )

    def _data(self, **overrides):
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

    def test_valid_data(self):
        form = OrderForm(self._data())

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["eve_type"], self.eve_type)
        self.assertEqual(form.cleaned_data["quantity"], 500)
        self.assertEqual(form.cleaned_data["destination"], "Jita")

    def test_access_level_becomes_a_number(self):
        form = OrderForm(self._data(access_level="2"))

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["access_level"], Order.AccessLevel.MIDDLE)
        self.assertIsInstance(form.cleaned_data["access_level"], int)

    def test_destination_and_note_are_optional(self):
        data = self._data()
        del data["destination"]
        del data["note"]

        self.assertTrue(OrderForm(data).is_valid())

    def test_item_must_be_picked(self):
        form = OrderForm(self._data(eve_type_id=""))

        self.assertFalse(form.is_valid())
        self.assertIn("eve_type_id", form.errors)

    def test_item_must_be_in_the_catalog(self):
        for type_id in ("1", "424242"):  # other category, unknown id
            with self.subTest(type_id=type_id):
                form = OrderForm(self._data(eve_type_id=type_id))

                self.assertFalse(form.is_valid())
                self.assertIn("eve_type_id", form.errors)

    def test_invalid_values_are_rejected(self):
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        bad_values = {
            "quantity": "0",
            "unit_price": "-1",
            "priority": "URGENT",
            "access_level": "9",
            "due_date": yesterday,
        }

        for field, value in bad_values.items():
            with self.subTest(field=field):
                form = OrderForm(self._data(**{field: value}))

                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_defaults_for_a_new_form(self):
        form = OrderForm()

        self.assertEqual(form.fields["access_level"].initial, Order.AccessLevel.BASE)
        self.assertEqual(form.fields["priority"].initial, Order.Priority.MEDIUM)