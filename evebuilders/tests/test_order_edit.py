"""Editing an order (Discord is mocked out)"""

# Standard Library
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

# Third Party
# EVE Universe
from eveuniverse.models import EveType

# Django
from django.contrib.messages import constants, get_messages
from django.core.exceptions import ValidationError
from django.test import Client, SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

# AA EVE Builders
from evebuilders.forms import OrderEditForm
from evebuilders.manager_actions import item_is_locked, update_order
from evebuilders.messages import display_name, show_value
from evebuilders.models import ContractRecord, Order, OrderEvent
from evebuilders.notifications import CHANNEL_NEW_ORDER, EMOJI_CHANGED
from evebuilders.tests.test_messages import fields_of
from evebuilders.tests.test_notifications import SettingsMixin
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES

DELAY = "evebuilders.tasks.send_discord_notification.delay"
URL = "https://discord.com/api/webhooks/1/abc"


class TestShowValue(SimpleTestCase):
    """show_value"""

    def test_values_are_shown_plainly(self):
        self.assertEqual(show_value("unit_price", Decimal("1000000.00")), "1000000")
        self.assertEqual(show_value("unit_price", Decimal("0.50")), "0.5")
        self.assertEqual(show_value("access_level", 2), "Middle")
        self.assertEqual(show_value("due_date", date(2026, 11, 8)), "2026-11-08")
        self.assertEqual(
            show_value("eve_type", SimpleNamespace(name="Punisher")), "Punisher"
        )
        self.assertEqual(show_value("quantity", 10), "10")
        self.assertEqual(show_value("priority", "HIGH"), "HIGH")

    def test_empty_values(self):
        self.assertEqual(show_value("note", ""), "<пусто>")
        self.assertEqual(show_value("note", None, empty="(empty)"), "(empty)")


class EditTestCase(SettingsMixin, ViewsTestCase):
    """An order of 1000 Punishers at 1 000 000 ISK, Base level, medium priority"""

    def _update(self, actor=None, **values):
        return update_order(
            actor=actor or self.manager, order_id=self.order.pk, values=values
        )

    def _refresh(self):
        self.order.refresh_from_db()

    def _events(self):
        return OrderEvent.objects.filter(kind=OrderEvent.Kind.UPDATED)


class TestUpdateOrder(EditTestCase):
    """update_order"""

    def test_changes_are_applied_and_written_to_the_history(self):
        changes = self._update(quantity=1200, priority=Order.Priority.HIGH)

        self._refresh()
        self.assertEqual({change.field for change in changes}, {"quantity", "priority"})
        self.assertEqual(self.order.quantity, 1200)
        self.assertEqual(self.order.priority, Order.Priority.HIGH)
        self.assertEqual(self.order.updated_by, self.manager)
        event = self._events().get()
        self.assertEqual(event.actor, self.manager)
        self.assertIn("quantity: 1000 -> 1200", event.description)
        self.assertIn("priority: MEDIUM -> HIGH", event.description)

    def test_values_that_did_not_change_do_nothing(self):
        changes = self._update(quantity=1000, priority="MEDIUM")

        self.assertEqual(changes, [])
        self.assertFalse(self._events().exists())

    def test_the_quantity_cannot_go_below_what_is_taken(self):
        self._take(self.builder, 400)

        with self.assertRaises(ValidationError):
            self._update(quantity=399)

        self._refresh()
        self.assertEqual(self.order.quantity, 1000)

    def test_the_quantity_may_equal_what_is_taken(self):
        self._take(self.builder, 400)

        self._update(quantity=400)

        self._refresh()
        self.assertEqual(self.order.status, Order.Status.DISTRIBUTED)

    def test_raising_the_quantity_reopens_a_distributed_order(self):
        self._take(self.builder, 1000)
        self._refresh()
        self.assertEqual(self.order.status, Order.Status.DISTRIBUTED)

        self._update(quantity=1500)

        self._refresh()
        self.assertEqual(self.order.status, Order.Status.IN_PROGRESS)

    def test_the_item_can_change_only_while_nobody_took_the_order(self):
        rifter = EveType.objects.create(
            id=587, name="Rifter", eve_group=self.eve_type.eve_group, published=True
        )

        self.assertFalse(item_is_locked(self.order))
        self._update(eve_type=rifter)
        self._refresh()
        self.assertEqual(self.order.eve_type, rifter)

        self._take(self.builder, 10)
        self.assertTrue(item_is_locked(self.order))
        with self.assertRaises(ValidationError):
            self._update(eve_type=self.eve_type)

    def test_the_price_cannot_change_while_contracts_wait(self):
        share = self._take(self.builder, 400)
        record = ContractRecord.objects.create(
            contract_id=1,
            order=self.order,
            assignment=share,
            issuer_character_id=1,
            quantity=100,
            state=ContractRecord.State.OUTSTANDING,
        )

        with self.assertRaises(ValidationError):
            self._update(unit_price=Decimal("2000000.00"))

        ContractRecord.objects.filter(pk=record.pk).update(
            state=ContractRecord.State.CLOSED
        )
        self._update(unit_price=Decimal("2000000.00"))
        self._refresh()
        self.assertEqual(self.order.unit_price, Decimal("2000000.00"))

    def test_finished_and_cancelled_orders_cannot_be_changed(self):
        for status in (Order.Status.COMPLETED, Order.Status.CANCELLED):
            with self.subTest(status=status):
                Order.objects.filter(pk=self.order.pk).update(status=status)

                with self.assertRaises(ValidationError):
                    self._update(quantity=5)

    def test_only_managers_can_change_orders(self):
        with self.assertRaises(ValidationError):
            self._update(actor=self.builder, quantity=5)

        self._refresh()
        self.assertEqual(self.order.quantity, 1000)

    def test_invalid_values_are_refused_and_nothing_changes(self):
        for values in (
            {"quantity": 0},
            {"unit_price": Decimal("-1")},
            {"access_level": 9},
        ):
            with self.subTest(values=values):
                with self.assertRaises(ValidationError):
                    self._update(**values)

        self._refresh()
        self.assertEqual(self.order.quantity, 1000)
        self.assertEqual(self.order.unit_price, Decimal("1000000.00"))
        self.assertFalse(self._events().exists())

    def test_the_change_is_announced_with_what_it_was_and_what_it_is(self):
        self.configure(NEW_ORDER_WEBHOOK_URL=URL, NEW_ORDER_THREAD_ID="")

        with patch(DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self._update(quantity=1200, destination="Jita")

        delay.assert_called_once()
        channel, payload = delay.call_args.args
        self.assertEqual(channel, CHANNEL_NEW_ORDER)
        lines = payload["embeds"][0]["description"].splitlines()
        self.assertEqual(
            lines[0],
            f"{EMOJI_CHANGED} Заказ {self.order.number} был изменен "
            f"{display_name(self.manager)}",
        )
        fields = fields_of(payload)
        self.assertEqual(fields["Количество"], "1000 -> 1200")
        self.assertEqual(fields["Доставка"], "<пусто> -> Jita")

    def test_nothing_is_announced_when_nothing_changed(self):
        self.configure(NEW_ORDER_WEBHOOK_URL=URL, NEW_ORDER_THREAD_ID="")

        with patch(DELAY) as delay:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                self._update(quantity=1000)

        self.assertEqual(callbacks, [])
        delay.assert_not_called()


class TestOrderEditForm(EditTestCase):
    """OrderEditForm"""

    def _data(self, **overrides):
        data = {
            "item_text": "Punisher",
            "eve_type_id": str(self.eve_type.pk),
            "quantity": "1000",
            "unit_price": "1000000.00",
            "priority": "MEDIUM",
            "due_date": self.order.due_date.isoformat(),
            "access_level": "1",
            "destination": "",
            "note": "",
        }
        data.update(overrides)

        return data

    def _form(self, data, locked=False):
        return OrderEditForm(
            data,
            initial={"eve_type_id": self.order.eve_type_id},
            order=self.order,
            item_locked=locked,
        )

    def test_an_unchanged_date_in_the_past_is_fine(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        Order.objects.filter(pk=self.order.pk).update(due_date=yesterday)
        self.order.refresh_from_db()

        form = self._form(self._data(due_date=yesterday.isoformat()))

        self.assertTrue(form.is_valid(), form.errors)

    def test_a_new_date_in_the_past_is_refused(self):
        yesterday = timezone.localdate() - timedelta(days=1)

        form = self._form(self._data(due_date=yesterday.isoformat()))

        self.assertFalse(form.is_valid())
        self.assertIn("due_date", form.errors)

    def test_a_locked_item_ignores_what_is_posted(self):
        form = self._form(self._data(eve_type_id="424242"), locked=True)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["eve_type"], self.order.eve_type)


@override_settings(STORAGES=TEST_STORAGES)
class TestEditOrderPages(EditTestCase):
    """The edit page"""

    def _url(self, order=None):
        return reverse("evebuilders:edit_order", args=[(order or self.order).pk])

    def _post(self, data, user=None):
        client = Client()  # fresh client: no messages left over from before
        client.force_login(user or self.manager)

        return client.post(self._url(), data)

    def _data(self, **overrides):
        data = {
            "item_text": "Punisher",
            "eve_type_id": str(self.eve_type.pk),
            "quantity": "1000",
            "unit_price": "1000000.00",
            "priority": "MEDIUM",
            "due_date": self.order.due_date.isoformat(),
            "access_level": "1",
            "destination": "",
            "note": "",
        }
        data.update(overrides)

        return data

    @staticmethod
    def _levels(response):
        return [m.level for m in get_messages(response.wsgi_request)]

    def test_anonymous_and_builders_are_sent_away(self):
        self.assertEqual(self.client.get(self._url()).status_code, 302)

        self.client.force_login(self.builder)
        self.assertEqual(self.client.get(self._url()).status_code, 302)
        self.assertEqual(self.client.post(self._url(), self._data()).status_code, 302)

    def test_the_form_is_filled_with_the_order(self):
        self.client.force_login(self.manager)

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edit order")
        self.assertContains(response, 'value="1000"')
        self.assertContains(response, "Punisher")

    def test_the_item_is_locked_once_the_order_is_taken(self):
        self._take(self.builder, 10)
        self.client.force_login(self.manager)

        response = self.client.get(self._url())

        self.assertContains(response, "cannot be changed because builders")

    def test_a_valid_change(self):
        response = self._post(self._data(quantity="1200"))

        self.assertRedirects(
            response,
            reverse("evebuilders:order_detail", args=[self.order.pk]),
            fetch_redirect_response=False,
        )
        self._refresh()
        self.assertEqual(self.order.quantity, 1200)
        self.assertEqual(self._levels(response), [constants.SUCCESS])

    def test_nothing_changed_is_only_an_info(self):
        response = self._post(self._data())

        self.assertEqual(self._levels(response), [constants.INFO])
        self.assertFalse(self._events().exists())

    def test_a_refused_change_shows_the_reason(self):
        self._take(self.builder, 400)

        response = self._post(self._data(quantity="300"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already taken")
        self._refresh()
        self.assertEqual(self.order.quantity, 1000)

    def test_a_finished_order_cannot_be_changed(self):
        Order.objects.filter(pk=self.order.pk).update(status=Order.Status.COMPLETED)

        response = self._post(self._data(quantity="5"))

        self.assertContains(response, "cannot be changed")

    def test_the_details_page_has_the_edit_button_for_open_orders_only(self):
        self.client.force_login(self.manager)
        link = f'href="{self._url()}"'

        open_page = self.client.get(
            reverse("evebuilders:order_detail", args=[self.order.pk])
        )
        Order.objects.filter(pk=self.order.pk).update(status=Order.Status.COMPLETED)
        closed_page = self.client.get(
            reverse("evebuilders:order_detail", args=[self.order.pk])
        )

        self.assertContains(open_page, link)
        self.assertNotContains(closed_page, link)
