"""Places orders can be delivered to: public ESI lookups and the saved list"""

# Third Party
import requests

# Django
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

# AA EVE Builders
from evebuilders import __version__
from evebuilders.contracts import ESI_BASE_URL, EsiError, EsiUnavailable
from evebuilders.models import Destination, SolarSystem
from evebuilders.permissions import MANAGE_ACCESS

PLACES_TIMEOUT = 15  # seconds
SEARCH_MIN_LENGTH = 3
SEARCH_LIMIT = 10  # systems shown for a search
NAMES_CHUNK = 1000  # how many IDs ESI resolves to names in one request


class PlaceNotFound(EsiError):
    """ESI does not know the system or station"""


def _call(method: str, path: str, **kwargs):
    """One request to the public ESI, the answer as JSON"""

    try:
        response = requests.request(
            method,
            f"{ESI_BASE_URL}{path}",
            headers={"User-Agent": f"aa-eve-builders/{__version__}"},
            timeout=PLACES_TIMEOUT,
            **kwargs,
        )
    except requests.RequestException as ex:
        raise EsiUnavailable(f"The ESI request failed: {ex}") from ex

    if response.status_code == 404:
        raise PlaceNotFound(path)

    if response.status_code != 200:
        raise EsiUnavailable(
            f"ESI answered HTTP {response.status_code}: {response.text[:200]}"
        )

    return response.json()


def fetch_system(system_id: int) -> dict:
    """A solar system: its ID, name and the IDs of its NPC stations"""

    data = _call("GET", f"/universe/systems/{system_id}/")

    return {
        "id": system_id,
        "name": data["name"],
        "station_ids": list(data.get("stations", [])),
    }


def fetch_station(station_id: int) -> dict:
    """An NPC station: its ID, name and the ID of its system"""

    data = _call("GET", f"/universe/stations/{station_id}/")

    return {"id": station_id, "name": data["name"], "system_id": data["system_id"]}


def load_system_index() -> int:
    """
    Copy the names of all solar systems from ESI into the local index. The
    old index is replaced only when everything was read.

    :raises evebuilders.contracts.EsiError: When ESI cannot be read
    :return: How many systems are in the index now
    """

    system_ids = _call("GET", "/universe/systems/")

    systems = []
    for start in range(0, len(system_ids), NAMES_CHUNK):
        chunk = system_ids[start : start + NAMES_CHUNK]
        for entry in _call("POST", "/universe/names/", json=chunk):
            if entry.get("category") == "solar_system":
                systems.append(SolarSystem(id=entry["id"], name=entry["name"]))

    with transaction.atomic():
        SolarSystem.objects.all().delete()
        SolarSystem.objects.bulk_create(systems, batch_size=1000)

    return len(systems)


def search_systems(query: str) -> list[dict]:
    """
    Solar systems whose name matches the query, sorted by name.

    An exact name (any letter case) wins: if there is one, only it is
    returned. Otherwise the systems whose name contains the text are returned
    (at most SEARCH_LIMIT). The names come from the local index, which is
    loaded from ESI the first time it is needed.

    :return: [{"id", "name"}, ...]
    """

    query = query.strip()
    if len(query) < SEARCH_MIN_LENGTH:
        return []

    if not SolarSystem.objects.exists():
        load_system_index()

    found = list(SolarSystem.objects.filter(name__iexact=query)) or list(
        SolarSystem.objects.filter(name__icontains=query).order_by("name")[
            :SEARCH_LIMIT
        ]
    )

    return [{"id": system.id, "name": system.name} for system in found]


def system_stations(system_id: int) -> dict:
    """
    A solar system with its NPC stations, sorted by name.

    :return: {"system": {"id", "name"}, "stations": [{"id", "name"}, ...]}
    """

    system = fetch_system(system_id)

    stations: list = []
    if system["station_ids"]:
        names = _call("POST", "/universe/names/", json=system["station_ids"])
        stations = sorted(
            (
                {"id": entry["id"], "name": entry["name"]}
                for entry in names
                if entry.get("category") == "station"
            ),
            key=lambda station: station["name"].lower(),
        )

    return {
        "system": {"id": system["id"], "name": system["name"]},
        "stations": stations,
    }


def add_destination(
    *,
    actor,
    system_id: int,
    station_id: int | None = None,
    structure_name: str = "",
) -> Destination:
    """
    Add a place to the list (managers only).

    ESI is asked again for the names, so nothing that was posted by a browser
    is trusted. A station is saved under its own name. A system is saved
    under its name, followed by the structure name if one was typed.

    :raises django.core.exceptions.ValidationError: When it cannot be added
    :raises evebuilders.contracts.EsiError: When ESI cannot be read or does not
        know the system or station
    :return: The new place
    """

    if not actor.has_perm(MANAGE_ACCESS):
        raise ValidationError(_("Only managers can do this."))

    system = fetch_system(system_id)

    if station_id is not None:
        station = fetch_station(station_id)
        if station["system_id"] != system_id:
            raise ValidationError(_("This station is not in that system."))

        label = station["name"]
        structure_name = ""
    else:
        structure_name = " ".join((structure_name or "").split())[:150]
        label = (
            f"{system['name']} - {structure_name}" if structure_name else system["name"]
        )

    if Destination.objects.filter(label=label).exists():
        raise ValidationError(_("This place is already in the list."))

    return Destination.objects.create(
        label=label,
        system_id=system_id,
        system_name=system["name"],
        station_id=station_id,
        structure_name=structure_name,
        created_by=actor,
    )
