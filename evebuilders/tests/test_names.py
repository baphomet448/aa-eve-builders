"""Names of characters: Auth, what eveuniverse kept, and ESI"""

# Standard Library
from unittest.mock import patch

# Third Party
# EVE Universe
from eveuniverse.models import EveEntity

# Django
from django.test import TestCase

# AA EVE Builders
from evebuilders.names import character_name, character_names
from evebuilders.tests.test_views import make_user

RESOLVE = "evebuilders.names.EveEntity.objects.bulk_resolve_ids"


def keep(character_id: int, name: str) -> None:
    """What eveuniverse keeps after ESI told a name"""

    EveEntity.objects.update_or_create(
        id=character_id,
        defaults={"name": name, "category": EveEntity.CATEGORY_CHARACTER},
    )


class TestNames(TestCase):
    """character_names and character_name"""

    def test_a_character_of_auth_is_known(self):
        character = make_user("pilot", "builder_access").profile.main_character

        self.assertEqual(
            character_names([character.character_id]),
            {character.character_id: character.character_name},
        )

    def test_a_name_that_eveuniverse_kept_needs_no_esi(self):
        keep(98698983, "Old Officer")

        with patch(RESOLVE) as resolve:
            name = character_name(98698983)

        self.assertEqual(name, "Old Officer")
        resolve.assert_not_called()

    def test_an_unknown_name_is_asked_from_esi_and_kept(self):
        def esi(ids):
            for character_id in ids:
                keep(character_id, "Far Officer")

        with patch(RESOLVE, side_effect=esi) as resolve:
            name = character_name(111)

        self.assertEqual(name, "Far Officer")
        resolve.assert_called_once()
        self.assertEqual(EveEntity.objects.get(id=111).name, "Far Officer")

    def test_a_page_does_not_ask_esi(self):
        with patch(RESOLVE) as resolve:
            names = character_names([111])

        self.assertEqual(names, {})
        resolve.assert_not_called()

    def test_when_esi_is_down_the_id_is_shown(self):
        with patch(RESOLVE, side_effect=RuntimeError("down")):
            self.assertEqual(character_name(111), "111")

    def test_zero_and_empty_ids_are_ignored(self):
        self.assertEqual(character_names([0, None]), {})
