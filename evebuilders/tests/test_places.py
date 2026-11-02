"""Places orders can be delivered to (the public ESI is mocked out)"""

# Standard Library
from unittest.mock import MagicMock, patch

# Third Party
import requests

# Django
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

# AA EVE Builders
from evebuilders.contracts import ESI_BASE_URL, EsiUnavailable
from evebuilders.models import Destination
from evebuilders.places import (
    PlaceNotFound,
    add_destination,
    fetch_station,
    fetch_system,
    search_systems,
    system_stations,
)
from evebuilders.tests.test_views import make_user

REQUEST = "evebuilders.places.requests.request"
JITA = 30000142
JITA_STATION = 60003760
JITA_OTHER = 60000361
STATION_NAME = "Jita IV - Moon 4 - Caldari Navy Assembly Plant"
OTHER_NAME = "Jita IV - Moon 4 - Another Station"


class FakeEsi:
    """A stand-in for requests.request: answers from a table of routes"""

    def __init__(self):
        self.routes = {}
        self.calls = []

    def add(self, method, path, data=None, status=200, strict=None):
        self.routes[(method, path, strict)] = (status, data)

    def __call__(self, method, url, **kwargs):
        path = url.removeprefix(ESI_BASE_URL)
        strict = (kwargs.get("params") or {}).get("strict") if path == "/search/" else None
        self.calls.append((method, path, strict))
        status, data = self.routes.get((method, path, strict), (404, None))

        response = MagicMock()
        response.status_code = status
        response.json.return_value = data
        response.text = "body"

        return response

    def paths(self):
        return [call[1] for call in self.calls]


def jita_esi() -> FakeEsi:
    """Jita (two stations) and a second system that has no stations"""

    esi = FakeEsi()
    esi.add("GET", f"/universe/systems/{JITA}/", {"name": "Jita", "stations": [JITA_STATION, JITA_OTHER]})
    esi.add("GET", "/universe/systems/31000005/", {"name": "J100357"})
    esi.add("GET", f"/universe/stations/{JITA_STATION}/", {"name": STATION_NAME, "system_id": JITA})
    esi.add(
        "POST",
        "/universe/names/",
        [
            {"category": "station", "id": JITA_OTHER, "name": OTHER_NAME},
            {"category": "station", "id": JITA_STATION, "name": STATION_NAME},
        ],
    )

    return esi


class TestSearchSystems(SimpleTestCase):
    """search_systems"""

    def test_a_short_query_asks_nobody(self):
        esi = jita_esi()

        with patch(REQUEST, side_effect=esi):
            self.assertEqual(search_systems("Ji"), [])
            self.assertEqual(search_systems("  "), [])

        self.assertEqual(esi.calls, [])

    def test_an_exact_name_wins(self):
        esi = jita_esi()
        esi.add("GET", "/search/", {"solar_system": [JITA]}, strict="true")

        with patch(REQUEST, side_effect=esi):
            result = search_systems("Jita")

        self.assertEqual(
            result, [{"id": JITA, "name": "Jita", "station_ids": [JITA_STATION, JITA_OTHER]}]
        )
        self.assertNotIn(("GET", "/search/", "false"), esi.calls)

    def test_a_part_of_the_name_finds_several_systems_sorted_by_name(self):
        esi = jita_esi()
        esi.add("GET", "/search/", {}, strict="true")
        esi.add("GET", "/search/", {"solar_system": [31000005, JITA]}, strict="false")

        with patch(REQUEST, side_effect=esi):
            result = search_systems("J")

        self.assertEqual(result, [])  # one letter is too short

        with patch(REQUEST, side_effect=esi):
            result = search_systems("Jit")

        self.assertEqual([system["name"] for system in result], ["J100357", "Jita"])

    def test_nothing_found(self):
        esi = FakeEsi()
        esi.add("GET", "/search/", {}, strict="true")
        esi.add("GET", "/search/", {}, strict="false")

        with patch(REQUEST, side_effect=esi):
            self.assertEqual(search_systems("Nowhere"), [])

    def test_at_most_ten_systems_are_shown(self):
        esi = FakeEsi()
        ids = list(range(31000001, 31000016))
        esi.add("GET", "/search/", {}, strict="true")
        esi.add("GET", "/search/", {"solar_system": ids}, strict="false")
        for system_id in ids:
            esi.add("GET", f"/universe/systems/{system_id}/", {"name": f"J{system_id}"})

        with patch(REQUEST, side_effect=esi):
            result = search_systems("J31")

        self.assertEqual(len(result), 10)

    def test_esi_problems_are_reported(self):
        esi = FakeEsi()
        esi.add("GET", "/search/", None, status=500, strict="true")

        with patch(REQUEST, side_effect=esi):
            with self.assertRaises(EsiUnavailable):
                search_systems("Jita")

        with patch(REQUEST, side_effect=requests.ConnectionError("no network")):
            with self.assertRaises(EsiUnavailable):
                search_systems("Jita")


class TestSystemStations(SimpleTestCase):
    """system_stations and the single lookups"""

    def test_the_stations_come_with_names_sorted(self):
        esi = jita_esi()

        with patch(REQUEST, side_effect=esi):
            result = system_stations(JITA)

        self.assertEqual(result["system"], {"id": JITA, "name": "Jita"})
        self.assertEqual(
            [station["name"] for station in result["stations"]], [OTHER_NAME, STATION_NAME]
        )
        self.assertEqual(esi.paths().count("/universe/names/"), 1)

    def test_a_system_without_stations(self):
        esi = jita_esi()

        with patch(REQUEST, side_effect=esi):
            result = system_stations(31000005)

        self.assertEqual(result["stations"], [])
        self.assertNotIn("/universe/names/", esi.paths())

    def test_an_unknown_system(self):
        with patch(REQUEST, side_effect=FakeEsi()):
            with self.assertRaises(PlaceNotFound):
                system_stations(1)

    def test_single_lookups(self):
        esi = jita_esi()

        with patch(REQUEST, side_effect=esi):
            self.assertEqual(fetch_system(31000005)["station_ids"], [])
            self.assertEqual(
                fetch_station(JITA_STATION),
                {"id": JITA_STATION, "name": STATION_NAME, "system_id": JITA},
            )


class TestAddDestination(TestCase):
    """add_destination"""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.manager = make_user("manager", "manage_access")
        cls.builder = make_user("builder", "builder_access")

    def _add(self, actor=None, **kwargs):
        with patch(REQUEST, side_effect=jita_esi()):
            return add_destination(actor=actor or self.manager, **kwargs)

    def test_a_station_is_saved_under_its_own_name(self):
        place = self._add(system_id=JITA, station_id=JITA_STATION)

        self.assertEqual(place.label, STATION_NAME)
        self.assertEqual(place.system_id, JITA)
        self.assertEqual(place.system_name, "Jita")
        self.assertEqual(place.station_id, JITA_STATION)
        self.assertEqual(place.structure_name, "")
        self.assertEqual(place.created_by, self.manager)

    def test_a_station_of_another_system_is_refused(self):
        with self.assertRaises(ValidationError):
            self._add(system_id=31000005, station_id=JITA_STATION)

        self.assertFalse(Destination.objects.exists())

    def test_a_system_with_a_structure_name(self):
        place = self._add(system_id=31000005, structure_name="  Fortizar   Alpha ")

        self.assertEqual(place.label, "J100357 - Fortizar Alpha")
        self.assertIsNone(place.station_id)
        self.assertEqual(place.structure_name, "Fortizar Alpha")

    def test_a_system_alone(self):
        place = self._add(system_id=31000005)

        self.assertEqual(place.label, "J100357")
        self.assertEqual(place.structure_name, "")

    def test_the_same_place_cannot_be_added_twice(self):
        self._add(system_id=JITA, station_id=JITA_STATION)

        with self.assertRaises(ValidationError):
            self._add(system_id=JITA, station_id=JITA_STATION)

        self.assertEqual(Destination.objects.count(), 1)

    def test_only_managers_can_add(self):
        with self.assertRaises(ValidationError):
            self._add(actor=self.builder, system_id=JITA)

        self.assertFalse(Destination.objects.exists())

    def test_an_unknown_system_is_an_esi_problem_not_a_place(self):
        with patch(REQUEST, side_effect=FakeEsi()):
            with self.assertRaises(PlaceNotFound):
                add_destination(actor=self.manager, system_id=1)

        self.assertFalse(Destination.objects.exists())