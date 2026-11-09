"""The texts of the Discord notifications"""

# Django
from django.contrib.auth import get_user_model
from django.test import override_settings

# AA EVE Builders
from evebuilders.messages import discard_payload, display_name, new_order_payload
from evebuilders.tests.test_take_discard_views import ViewsTestCase

User = get_user_model()


def fields_of(payload) -> dict:
    """The embed fields of a payload as a dict"""

    return {f["name"]: f["value"] for f in payload["embeds"][0].get("fields", [])}


class TestNewOrderPayload(ViewsTestCase):
    """new_order_payload"""

    @override_settings(SITE_URL="https://auth.example.com")
    def test_has_the_usual_fields(self):
        payload = new_order_payload(self.order)

        fields = fields_of(payload)
        self.assertEqual(fields["Заказ"], self.order.number)
        self.assertEqual(fields["Наименование"], "Punisher")
        self.assertEqual(fields["Количество"], "1000")
        self.assertEqual(fields["Цена за единицу"], "1 000 000 ISK")
        self.assertEqual(fields["Приоритет"], "MEDIUM")
        self.assertEqual(
            fields["Взять заказ:"], "https://auth.example.com/evebuilders/orders/"
        )
        self.assertEqual(fields["Срок сдачи до"], self.order.due_date.isoformat())
        self.assertNotIn("Уровень доступа", fields)
        self.assertNotIn("description", payload["embeds"][0])

    def test_higher_levels_are_marked(self):
        fields = fields_of(new_order_payload(self.middle))

        self.assertEqual(fields["Уровень доступа"], "Middle")

    @override_settings(SITE_URL="")
    def test_without_a_site_url_there_is_no_link(self):
        fields = fields_of(new_order_payload(self.order))

        self.assertNotIn("Взять заказ:", fields)


class TestDiscardPayload(ViewsTestCase):
    """discard_payload"""

    def test_reports_what_was_given_back(self):
        payload = discard_payload(
            user=self.builder, order=self.order, quantity=5, free=995
        )

        name = display_name(self.builder)
        self.assertEqual(
            payload["embeds"][0]["description"].splitlines(),
            [
                f"Отчет от - {name}",
                "Отказ от 5 позиций",
                "Сумма 5 000 000 ISK 5 миллионов",
                "ОТМЕНА",
            ],
        )
        fields = fields_of(payload)
        self.assertEqual(fields["Заказ"], f"{self.order.number} - Отменен")
        self.assertEqual(fields["Наименование"], "Punisher")
        self.assertEqual(fields["Свободно в заказе"], "995 шт")


class TestDisplayName(ViewsTestCase):
    """display_name"""

    def test_the_main_character_is_used(self):
        self.assertEqual(
            display_name(self.builder),
            self.builder.profile.main_character.character_name,
        )

    def test_without_a_main_character_the_login_is_used(self):
        user = User.objects.create_user("plain")

        self.assertEqual(display_name(user), "plain")
