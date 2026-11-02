"""The places page and the list of destinations in the order forms"""

# Standard Library
from datetime import timedelta
from unittest.mock import patch

# Third Party
import requests

# Django
from django.contrib.messages import constants, get_messages
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

# AA EVE Builders
from evebuilders.contracts import EsiUnavailable
from evebuilders.forms import OrderEditForm, OrderForm
from evebuilders.messages import new_order_payload
from evebuilders.models import Destination
from evebuilders.tests.test_messages import fields_of
from evebuilders.tests.test_places import (
    JITA,
    JITA_STATION,
    REQUEST,
    STATION_NAME,
    WORMHOLE,
    jita_esi,
)
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES

VIEWS = "evebuilders.views"


class PlacesTestCase(ViewsTestCase):
    """A manager, a builder and some helpers"""

    def _place(self, label=STATION_NAME, **extra):
        return Destination.objects.create(
            label=label, system_id=JITA, system_name="Jita", **extra
        )

    def _post(self, name, data=None, user=None, args=()):
        client = Client()  # fresh client: no messages left over from before
        client.force_login(user or self.manager)

        return client.post(reverse(f"evebuilders:{name}", args=args), data or {})

    @staticmethod
    def _levels(response):
        return [m.level for m in get_messages(response.wsgi_request)]


@override_settings(STORAGES=TEST_STORAGES)
class TestStationsPage(PlacesTestCase):
    """The page and its search"""

    def _get(self, **params):
        self.client.force_login(self.manager)

        return self.client.get(reverse("evebuilders:stations"), params)

    def test_anonymous_and_builders_are_sent_away(self):
        url = reverse("evebuilders:stations")

        self.assertEqual(self.client.get(url).status_code, 302)

        self.client.force_login(self.builder)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_the_saved_places_are_listed(self):
        place = self._place()

        response = self._get()

        self.assertContains(response, STATION_NAME)
        self.assertContains(
            response, reverse("evebuilders:delete_station", args=[place.pk])
        )

    def test_an_empty_list_says_so(self):
        self.assertContains(self._get(), "No places yet.")

    def test_one_system_shows_its_stations_and_the_system_form(self):
        found = {"system": {"id": JITA, "name": "Jita"}, "stations": [{"id": JITA_STATION, "name": STATION_NAME}]}

        with patch(f"{VIEWS}.search_systems", return_value=[{"id": JITA, "name": "Jita"}]):
            with patch(f"{VIEWS}.system_stations", return_value=found):
                response = self._get(q="Jita")

        self.assertContains(response, STATION_NAME)
        self.assertContains(response, reverse("evebuilders:add_station"))
        self.assertContains(response, "Add the system")

    def test_several_systems_are_offered_to_pick_from(self):
        systems = [{"id": JITA, "name": "Jita"}, {"id": 30000999, "name": "Jitaville"}]

        with patch(f"{VIEWS}.search_systems", return_value=systems):
            response = self._get(q="Jit")

        self.assertContains(response, f"?system={JITA}")
        self.assertContains(response, "Jitaville")

    def test_a_picked_system_shows_its_stations(self):
        found = {"system": {"id": JITA, "name": "Jita"}, "stations": [{"id": JITA_STATION, "name": STATION_NAME}]}

        with patch(f"{VIEWS}.system_stations", return_value=found):
            response = self._get(system=str(JITA))

        self.assertContains(response, STATION_NAME)

    def test_a_system_without_stations_can_still_be_added(self):
        found = {"system": {"id": WORMHOLE, "name": "J100357"}, "stations": []}

        with patch(f"{VIEWS}.system_stations", return_value=found):
            response = self._get(system=str(WORMHOLE))

        self.assertContains(response, "This system has no NPC stations.")
        self.assertContains(response, "Add the system")

    def test_nothing_found_and_a_short_query(self):
        with patch(f"{VIEWS}.search_systems", return_value=[]):
            nothing = self._get(q="Nowhere")
        short = self._get(q="Ji")

        self.assertContains(nothing, "No systems found.")
        self.assertContains(short, "Type at least 3 letters.")

    def test_an_esi_problem_is_shown(self):
        with patch(f"{VIEWS}.search_systems", side_effect=EsiUnavailable("down")):
            response = self._get(q="Jita")

        self.assertContains(response, "ESI could not be read")

    def test_the_settings_tabs_link_to_it(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:settings"))

        self.assertContains(response, reverse("evebuilders:stations"))


class TestAddAndRemovePlaces(PlacesTestCase):
    """The forms of the page"""

    def test_a_station_is_added(self):
        with patch(REQUEST, side_effect=jita_esi()):
            response = self._post(
                "add_station", {"system_id": JITA, "station_id": JITA_STATION}
            )

        self.assertRedirects(
            response, reverse("evebuilders:stations"), fetch_redirect_response=False
        )
        self.assertEqual(Destination.objects.get().label, STATION_NAME)
        self.assertEqual(self._levels(response), [constants.SUCCESS])

    def test_a_system_with_a_structure_is_added(self):
        with patch(REQUEST, side_effect=jita_esi()):
            self._post(
                "add_station",
                {"system_id": WORMHOLE, "structure_name": "Fortizar Alpha"},
            )

        self.assertEqual(Destination.objects.get().label, "J100357 - Fortizar Alpha")

    def test_the_same_place_twice_is_an_error(self):
        self._place()

        with patch(REQUEST, side_effect=jita_esi()):
            response = self._post(
                "add_station", {"system_id": JITA, "station_id": JITA_STATION}
            )

        self.assertEqual(self._levels(response), [constants.ERROR])
        self.assertEqual(Destination.objects.count(), 1)

    def test_bad_numbers_are_an_error(self):
        for data in ({"system_id": "abc"}, {"system_id": JITA, "station_id": "x"}):
            with self.subTest(data=data):
                response = self._post("add_station", data)

                self.assertEqual(self._levels(response), [constants.ERROR])

        self.assertFalse(Destination.objects.exists())

    def test_esi_being_down_is_an_error(self):
        with patch(REQUEST, side_effect=requests.ConnectionError("no network")):
            response = self._post("add_station", {"system_id": JITA})

        self.assertEqual(self._levels(response), [constants.ERROR])
        self.assertFalse(Destination.objects.exists())

    def test_a_place_is_removed(self):
        place = self._place()

        response = self._post("delete_station", args=[place.pk])

        self.assertRedirects(
            response, reverse("evebuilders:stations"), fetch_redirect_response=False
        )
        self.assertFalse(Destination.objects.exists())
        self.assertEqual(self._levels(response), [constants.SUCCESS])

    def test_builders_cannot_add_or_remove_and_get_is_not_allowed(self):
        place = self._place()

        added = self._post("add_station", {"system_id": JITA}, user=self.builder)
        removed = self._post("delete_station", user=self.builder, args=[place.pk])

        self.assertEqual(added.status_code, 302)
        self.assertEqual(removed.status_code, 302)
        self.assertEqual(Destination.objects.count(), 1)

        self.client.force_login(self.manager)
        self.assertEqual(
            self.client.get(reverse("evebuilders:add_station")).status_code, 405
        )


class TestDestinationInTheOrderForms(PlacesTestCase):
    """The destination is a list once there are places"""

    def _data(self, **overrides):
        data = {
            "item_text": "Punisher",
            "eve_type_id": str(self.eve_type.pk),
            "quantity": "10",
            "unit_price": "100.00",
            "priority": "MEDIUM",
            "due_date": (timezone.localdate() + timedelta(days=7)).isoformat(),
            "access_level": "1",
            "destination": "",
            "note": "",
        }
        data.update(overrides)

        return data

    def test_without_places_the_destination_is_free_text(self):
        form = OrderForm(self._data(destination="Anywhere I like"))

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["destination"], "Anywhere I like")

    def test_with_places_the_destination_must_be_one_of_them(self):
        self._place()

        good = OrderForm(self._data(destination=STATION_NAME))
        bad = OrderForm(self._data(destination="Anywhere I like"))
        empty = OrderForm(self._data(destination=""))

        self.assertTrue(good.is_valid(), good.errors)
        self.assertFalse(bad.is_valid())
        self.assertIn("destination", bad.errors)
        self.assertTrue(empty.is_valid(), empty.errors)

    def test_an_older_text_stays_a_choice_when_editing(self):
        self._place()
        self.order.destination = "Old text"

        form = OrderEditForm(
            self._data(destination="Old text"),
            initial={"eve_type_id": self.eve_type.pk},
            order=self.order,
            item_locked=False,
        )

        choices = [value for value, _label in form.fields["destination"].choices]
        self.assertIn("Old text", choices)
        self.assertIn(STATION_NAME, choices)
        self.assertTrue(form.is_valid(), form.errors)

    @override_settings(STORAGES=TEST_STORAGES)
    def test_the_order_page_shows_a_list(self):
        self._place()
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:new_order"))

        self.assertContains(response, '<select name="destination"')
        self.assertContains(response, STATION_NAME)

    def test_the_new_order_message_says_where_to(self):
        self.order.destination = "Jita IV"

        fields = fields_of(new_order_payload(self.order))

        self.assertEqual(fields["Доставка"], "Jita IV")

    def test_no_destination_no_field(self):
        self.order.destination = ""

        self.assertNotIn("Доставка", fields_of(new_order_payload(self.order)))