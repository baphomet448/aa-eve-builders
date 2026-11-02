"""Places orders can be delivered to (the public ESI is mocked out)"""

# Standard Library
from io import StringIO
from unittest.mock import MagicMock, patch

# Third Party
import requests

# Django
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

# AA EVE Builders
from evebuilders.contracts import ESI_BASE_URL, EsiUnavailable
from evebuilders.models import Destination, SolarSystem
from evebuilders.places import (
    PlaceNotFound,
    add_destination,
    fetch_station,
    fetch_system,
    load_system_index,
    search_systems,
    system_stations,
)
from evebuilders.tests.test_views import make_user

REQUEST = "evebuilders.places.requests.request"
JITA = 30000142
WORMHOLE = 31000005
JITAVILLE = 30000999
JITA_STATION = 60003760
JITA_OTHER = 60000361
STATION_NAME = "Jita IV - Moon 4 - Caldari Navy Assembly Plant"
OTHER_NAME = "Jita IV - Moon 4 - Another Station"

SYSTEMS = {JITA: "Jita", WORMHOLE: "J100357", JITAVILLE: "Jitaville"}
STATIONS = {JITA_STATION: STATION_NAME, JITA_OTHER: OTHER_NAME}


class FakeEsi:
    """A stand-in for requests.request: answers from a table of routes"""

    def __init__(self):
        self.routes = {}
        self.calls = []

    def add(self, method, path, data=None, status=200):
        self.routes[(method, path)] = (status, data)

    def __call__(self, method, url, **kwargs):
        path = url.removeprefix(ESI_BASE_URL)
        self.calls.append((method, path))
        status, data = self.routes.get((method, path), (404, None))
        if callable(data):
            data = data(kwargs)

        response = MagicMock()
        response.status_code = status
        response.json.return_value = data
        response.text = "body"

        return response

    def paths(self):
        return [call[1] for call in self.calls]


def names_answer(kwargs):
    """What POST /universe/names/ answers for the IDs it was given"""

    entries = []
    for entity_id in kwargs["json"]:
        if entity_id in SYSTEMS:
            entries.append(
                {
                    "category": "solar_system",
                    "id": entity_id,
                    "name": SYSTEMS[entity_id],
                }
            )
        if entity_id in STATIONS:
            entries.append(
                {"category": "station", "id": entity_id, "name": STATIONS[entity_id]}
            )

    return entries


def jita_esi() -> FakeEsi:
    """Three systems (Jita has two stations) and the lookups for them"""

    esi = FakeEsi()
    esi.add("GET", "/universe/systems/", list(SYSTEMS))
    esi.add(
        "GET",
        f"/universe/systems/{JITA}/",
        {"name": "Jita", "stations": [JITA_STATION, JITA_OTHER]},
    )
    esi.add("GET", f"/universe/systems/{WORMHOLE}/", {"name": "J100357"})
    esi.add(
        "GET",
        f"/universe/stations/{JITA_STATION}/",
        {"name": STATION_NAME, "system_id": JITA},
    )
    esi.add("POST", "/universe/names/", names_answer)

    return esi


class TestSystemIndex(TestCase):
    """load_system_index"""

    def test_it_copies_the_names_of_the_systems(self):
        with patch(REQUEST, side_effect=jita_esi()):
            count = load_system_index()

        self.assertEqual(count, 3)
        self.assertEqual(dict(SolarSystem.objects.values_list("id", "name")), SYSTEMS)

    def test_it_replaces_the_old_names(self):
        SolarSystem.objects.create(id=1, name="Stale")

        with patch(REQUEST, side_effect=jita_esi()):
            load_system_index()

        self.assertFalse(SolarSystem.objects.filter(id=1).exists())

    def test_names_that_are_not_systems_are_left_out(self):
        esi = jita_esi()
        esi.add(
            "POST",
            "/universe/names/",
            lambda kwargs: [
                {"category": "solar_system", "id": JITA, "name": "Jita"},
                {"category": "station", "id": JITA_STATION, "name": STATION_NAME},
            ],
        )

        with patch(REQUEST, side_effect=esi):
            load_system_index()

        self.assertEqual(SolarSystem.objects.count(), 1)

    def test_a_failure_keeps_the_old_index(self):
        SolarSystem.objects.create(id=1, name="Old")
        esi = jita_esi()
        esi.add("POST", "/universe/names/", None, status=500)

        with patch(REQUEST, side_effect=esi):
            with self.assertRaises(EsiUnavailable):
                load_system_index()

        self.assertEqual(SolarSystem.objects.get().name, "Old")

    def test_the_ids_are_asked_in_chunks(self):
        esi = FakeEsi()
        esi.add("GET", "/universe/systems/", list(range(1, 2501)))
        esi.add("POST", "/universe/names/", lambda kwargs: [])

        with patch(REQUEST, side_effect=esi):
            load_system_index()

        self.assertEqual(esi.paths().count("/universe/names/"), 3)  # 1000 + 1000 + 500


class TestSearchSystems(TestCase):
    """search_systems"""

    def test_a_short_query_asks_nobody(self):
        esi = jita_esi()

        with patch(REQUEST, side_effect=esi):
            self.assertEqual(search_systems("Ji"), [])
            self.assertEqual(search_systems("  "), [])

        self.assertEqual(esi.calls, [])

    def test_the_index_is_loaded_the_first_time_only(self):
        esi = jita_esi()

        with patch(REQUEST, side_effect=esi):
            search_systems("Jita")
            search_systems("Jita")

        self.assertEqual(esi.paths().count("/universe/systems/"), 1)

    def test_an_exact_name_wins_whatever_the_letter_case(self):
        with patch(REQUEST, side_effect=jita_esi()):
            result = search_systems("jita")

        self.assertEqual(result, [{"id": JITA, "name": "Jita"}])

    def test_a_part_of_the_name_finds_several_systems_sorted_by_name(self):
        with patch(REQUEST, side_effect=jita_esi()):
            result = search_systems("Jit")

        self.assertEqual([system["name"] for system in result], ["Jita", "Jitaville"])

    def test_a_part_of_a_wormhole_name(self):
        with patch(REQUEST, side_effect=jita_esi()):
            result = search_systems("j1003")

        self.assertEqual(result, [{"id": WORMHOLE, "name": "J100357"}])

    def test_nothing_found(self):
        with patch(REQUEST, side_effect=jita_esi()):
            self.assertEqual(search_systems("Nowhere"), [])

    def test_at_most_ten_systems_are_shown(self):
        SolarSystem.objects.bulk_create(
            [SolarSystem(id=i, name=f"Jxx{i:03d}") for i in range(15)]
        )

        self.assertEqual(len(search_systems("Jxx")), 10)

    def test_esi_problems_are_reported(self):
        with patch(REQUEST, side_effect=requests.ConnectionError("no network")):
            with self.assertRaises(EsiUnavailable):
                search_systems("Jita")

        self.assertFalse(SolarSystem.objects.exists())


class TestSystemStations(SimpleTestCase):
    """system_stations and the single lookups"""

    def test_the_stations_come_with_names_sorted(self):
        esi = jita_esi()

        with patch(REQUEST, side_effect=esi):
            result = system_stations(JITA)

        self.assertEqual(result["system"], {"id": JITA, "name": "Jita"})
        self.assertEqual(
            [station["name"] for station in result["stations"]],
            [OTHER_NAME, STATION_NAME],
        )
        self.assertEqual(esi.paths().count("/universe/names/"), 1)

    def test_a_system_without_stations(self):
        esi = jita_esi()

        with patch(REQUEST, side_effect=esi):
            result = system_stations(WORMHOLE)

        self.assertEqual(result["stations"], [])
        self.assertNotIn("/universe/names/", esi.paths())

    def test_an_unknown_system(self):
        with patch(REQUEST, side_effect=FakeEsi()):
            with self.assertRaises(PlaceNotFound):
                system_stations(1)

    def test_single_lookups(self):
        with patch(REQUEST, side_effect=jita_esi()):
            self.assertEqual(fetch_system(WORMHOLE)["station_ids"], [])
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
            self._add(system_id=WORMHOLE, station_id=JITA_STATION)

        self.assertFalse(Destination.objects.exists())

    def test_a_system_with_a_structure_name(self):
        place = self._add(system_id=WORMHOLE, structure_name="  Fortizar   Alpha ")

        self.assertEqual(place.label, "J100357 - Fortizar Alpha")
        self.assertIsNone(place.station_id)
        self.assertEqual(place.structure_name, "Fortizar Alpha")

    def test_a_system_alone(self):
        place = self._add(system_id=WORMHOLE)

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


class TestLoadSystemsCommand(SimpleTestCase):
    """evebuilders_load_systems"""

    COMMAND = "evebuilders.management.commands.evebuilders_load_systems"

    def test_it_says_how_many_systems_are_known(self):
        out = StringIO()

        with patch(f"{self.COMMAND}.load_system_index", return_value=8472):
            call_command("evebuilders_load_systems", stdout=out)

        self.assertIn("8472 solar systems", out.getvalue())

    def test_an_esi_problem_becomes_a_command_error(self):
        with patch(
            f"{self.COMMAND}.load_system_index", side_effect=EsiUnavailable("down")
        ):
            with self.assertRaises(CommandError):
                call_command("evebuilders_load_systems", stdout=StringIO())
