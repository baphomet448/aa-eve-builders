"""Names of characters: Auth knows some of them, ESI tells the others"""

# Standard Library
import logging

# Third Party
# EVE Universe
from eveuniverse.models import EveEntity

# Alliance Auth
from allianceauth.eveonline.models import EveCharacter

logger = logging.getLogger(__name__)


def _kept(ids) -> dict[int, str]:
    """The names that eveuniverse has already kept, by ID"""

    return dict(
        EveEntity.objects.filter(id__in=ids).exclude(name="").values_list("id", "name")
    )


def character_names(character_ids, *, resolve: bool = False) -> dict[int, str]:
    """
    The names of characters by their IDs.

    Auth knows the characters of its users. The others are read from what
    eveuniverse has kept, and with ``resolve`` the public ESI is asked for the
    rest (the answer is kept, so each name is asked for once).

    :param resolve: Ask ESI for the names nobody knows yet. Pages do not do this,
        they must not wait for ESI. The sync does it when it writes a name down.
    :return: A name for every ID that is known, the others are not in the dict
    """

    wanted = {int(character_id) for character_id in character_ids if character_id}

    names = dict(
        EveCharacter.objects.filter(character_id__in=wanted).values_list(
            "character_id", "character_name"
        )
    )

    missing = wanted - set(names)
    if missing:
        names.update(_kept(missing))
        missing = wanted - set(names)

    if missing and resolve:
        try:
            EveEntity.objects.bulk_resolve_ids(missing)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            # ESI is down or refuses: the ID is shown for now, a later run tries again
            logger.warning(
                "The names of the characters %s could not be resolved: %s",
                sorted(missing),
                ex,
            )
        else:
            names.update(_kept(missing))

    return names


def character_name(character_id: int, *, resolve: bool = True) -> str:
    """The name of a character, or its ID when nobody knows the name"""

    return character_names([character_id], resolve=resolve).get(
        int(character_id), str(character_id)
    )
