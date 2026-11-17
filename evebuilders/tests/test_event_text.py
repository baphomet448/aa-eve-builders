"""The texts of the history in English and in Russian"""

# Django
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

# AA EVE Builders
from evebuilders.event_text import describe, event_texts
from evebuilders.models import ContractRecord, Order, OrderEvent
from evebuilders.reasons import NOT_AVAILABLE, reason_fields
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES

Kind = OrderEvent.Kind

# The kind, the text as the plugin stores it, the English text, the Russian text
CASES = [
    (
        Kind.CREATED,
        "500 x 100MN Afterburner II, 3200000.00 ISK each",
        "500 × 100MN Afterburner II, 3,200,000 ISK each",
        "500 × 100MN Afterburner II, по 3 200 000 ISK",
    ),
    (
        Kind.TAKEN,
        "Took 5 (now 7 in total)",
        "Took 5 (now 7 in total)",
        "Взял 5 (всего у него 7)",
    ),
    (
        Kind.DISCARDED,
        "Gave back 2 (now 3 in total)",
        "Gave back 2 (now 3 in total)",
        "Вернул 2 (всего у него 3)",
    ),
    (
        Kind.RELEASED,
        "Released 2 from Gedeon Deka (now 3 in total)",
        "Released 2 from Gedeon Deka (now 3 in total)",
        "Освобождено 2 у Gedeon Deka (всего у него 3)",
    ),
    (
        Kind.CONTRACT_FOUND,
        "Contract 123 with 5 items waits for acceptance",
        "Contract 123 with 5 items waits for acceptance",
        "Контракт 123 на 5 шт. ждёт принятия",
    ),
    (
        Kind.CONTRACT_CLOSED,
        "Contract 123 ended without being accepted (expired)",
        "Contract 123 ended without being accepted (expired)",
        "Контракт 123 завершился без принятия (expired)",
    ),
    (
        Kind.CREDITED,
        "Credited 1 x Minmatar Shuttle (contract 238188077), accepted by Old Officer",
        "Delivered 1 × Minmatar Shuttle (contract 238188077), accepted by Old Officer",
        "Доставлено 1 × Minmatar Shuttle (контракт 238188077), принял: Old Officer",
    ),
    (
        Kind.CREDITED,
        "Credited 1 x Minmatar Shuttle (contract 5), accepted by unknown",
        "Delivered 1 × Minmatar Shuttle (contract 5), accepted by unknown",
        "Доставлено 1 × Minmatar Shuttle (контракт 5), принял: неизвестно",
    ),
    (
        Kind.MANUAL_CREDIT,
        "Credited 3 x Punisher manually",
        "Credited manually 3 × Punisher",
        "Зачтено вручную 3 × Punisher",
    ),
    (
        Kind.MANUAL_CREDIT,
        "Credited 3 x Punisher manually (contract 77): it was late",
        "Credited manually 3 × Punisher (contract 77): it was late",
        "Зачтено вручную 3 × Punisher (контракт 77): it was late",
    ),
    (
        Kind.CANCELLED,
        "Order cancelled",
        "Order cancelled",
        "Заказ отменён",
    ),
    (
        Kind.CANCELLED,
        "Order cancelled: duplicate",
        "Order cancelled: duplicate",
        "Заказ отменён: duplicate",
    ),
    (
        Kind.UPDATED,
        "Order changed: quantity: 500 -> 1500; price per unit: 10000 -> 2000000; "
        "note: (empty) -> hurry; priority: LOW -> HIGH",
        "Order changed: quantity: 500 → 1,500; price per unit: 10,000 → 2,000,000; "
        "note: (empty) → hurry; priority: LOW → HIGH",
        "Заказ изменён: количество: 500 → 1 500; цена за единицу: 10 000 → 2 000 000; "
        "примечание: (пусто) → hurry; приоритет: LOW → HIGH",
    ),
    (
        Kind.LEVEL_CHANGED,
        "Level of Gedeon Deka: Base -> Middle",
        "Level of Gedeon Deka: Base → Middle",
        "Уровень Gedeon Deka: Base → Middle",
    ),
    (
        Kind.ROLE_CHANGED,
        "Role of Gedeon Deka: Builder -> Manager",
        "Role of Gedeon Deka: Builder → Manager",
        "Роль Gedeon Deka: Строитель → Менеджер",
    ),
]


def say(kind, text: str, language: str, records=None) -> str:
    """The text of an event in a language (the separators of Russian are plain spaces)"""

    with translation.override(language):
        shown = describe(OrderEvent(kind=kind, description=text), records)

    return shown.replace("\xa0", " ")


class TestDescribe(TestCase):
    """The texts the plugin writes"""

    def test_every_text_is_translated(self):
        for kind, stored, english, russian in CASES:
            with self.subTest(kind=kind, text=stored):
                self.assertEqual(say(kind, stored, "en"), english)
                self.assertEqual(say(kind, stored, "ru"), russian)

    def test_a_text_the_plugin_does_not_know_stays_as_it_is(self):
        for kind in (Kind.TAKEN, Kind.CREATED, Kind.UPDATED, Kind.CREDITED):
            with self.subTest(kind=kind):
                self.assertEqual(say(kind, "Something else", "ru"), "Something else")

    def test_a_kind_without_a_text_stays_as_it_is(self):
        self.assertEqual(say(Kind.TOKEN_ERROR, "Boom", "ru"), "Boom")

    def test_the_reason_of_a_contract_is_translated_when_it_is_the_same(self):
        record = ContractRecord.objects.create(
            contract_id=7,
            issuer_character_id=1,
            state=ContractRecord.State.INVALID,
            **reason_fields(NOT_AVAILABLE),
        )
        text = f"Contract 7 cannot be counted: {record.reason}"

        russian = say(Kind.CONTRACT_INVALID, text, "ru", {7: record})

        self.assertTrue(russian.startswith("Контракт 7 нельзя засчитать: "))
        self.assertTrue(russian.endswith(record.reason_in("ru")))

    def test_a_different_reason_stays_as_it_was_written(self):
        record = ContractRecord.objects.create(
            contract_id=7,
            issuer_character_id=1,
            state=ContractRecord.State.INVALID,
            **reason_fields(NOT_AVAILABLE),
        )

        russian = say(
            Kind.CONTRACT_INVALID,
            "Contract 7 cannot be counted: an older reason",
            "ru",
            {7: record},
        )

        self.assertEqual(russian, "Контракт 7 нельзя засчитать: an older reason")

    def test_the_texts_of_many_events_ask_the_database_once(self):
        for number in (1, 2, 3):
            ContractRecord.objects.create(
                contract_id=number,
                issuer_character_id=1,
                state=ContractRecord.State.INVALID,
                **reason_fields(NOT_AVAILABLE),
            )
        events = [
            OrderEvent.objects.create(
                kind=Kind.CONTRACT_INVALID,
                description=f"Contract {number} cannot be counted: x",
            )
            for number in (1, 2, 3)
        ]

        with self.assertNumQueries(1):
            texts = event_texts(events)

        self.assertEqual(len(texts), 3)


@override_settings(STORAGES=TEST_STORAGES)
class TestOnThePages(ViewsTestCase):
    """The history of the management and of an order"""

    def _history(self, **params):
        self.client.force_login(self.manager)

        return self.client.get(reverse("evebuilders:management_history"), params)

    def _delivered_by_an_unknown_character(self) -> OrderEvent:
        return OrderEvent.objects.create(
            order=self.order,
            kind=Kind.CREDITED,
            actor_label="Old Officer",
            description="Credited 1 x Punisher (contract 5), accepted by Old Officer",
        )

    def test_the_label_of_the_event_is_delivered(self):
        self._delivered_by_an_unknown_character()

        response = self._history()

        self.assertContains(response, "Delivered")
        self.assertNotContains(response, ">Credited<")

    def test_the_details_are_translated_and_the_numbers_are_in_order(self):
        self._delivered_by_an_unknown_character()

        response = self._history()

        self.assertContains(
            response, "Delivered 1 × Punisher (contract 5), accepted by Old Officer"
        )
        self.assertContains(response, "1,000 × Punisher, 1,000,000 ISK each")

    def test_the_acceptor_stands_in_the_column_by(self):
        self._delivered_by_an_unknown_character()

        response = self._history()

        self.assertContains(response, "<td>Old Officer</td>")

    def test_the_filter_finds_an_event_by_the_acceptor(self):
        self._delivered_by_an_unknown_character()

        found = self._history(q="old officer").context["result"].rows
        nothing = self._history(q="nobody like that").context["result"].rows

        self.assertEqual([row["actor"] for row in found], ["Old Officer"])
        self.assertEqual(nothing, [])

    def test_the_sorting_by_who_did_it_counts_the_acceptor(self):
        self._delivered_by_an_unknown_character()
        OrderEvent.objects.create(
            order=self.order,
            kind=Kind.CREDITED,
            actor_label="Zed Officer",
            description="Credited 1 x Punisher (contract 6), accepted by Zed Officer",
        )

        rows = self._history(sort="actor", dir="desc").context["result"].rows

        names = [row["actor"] for row in rows]
        self.assertLess(names.index("Zed Officer"), names.index("Old Officer"))

    def test_the_history_of_an_order_is_translated_too(self):
        self._delivered_by_an_unknown_character()
        self.client.force_login(self.manager)

        response = self.client.get(
            reverse("evebuilders:order_detail", args=[self.order.pk])
        )

        self.assertContains(
            response, "Delivered 1 × Punisher (contract 5), accepted by Old Officer"
        )
        self.assertContains(response, "<td>Old Officer</td>")
        self.assertEqual(Order.objects.filter(pk=self.order.pk).count(), 1)
