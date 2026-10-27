"""ESI source tests"""

# Django
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

# Alliance Auth (External Libs)
from esi.models import Token

# AA EVE Builders
from evebuilders.contracts import connect_source
from evebuilders.models import ContractSource
from evebuilders.tests.test_views import TEST_STORAGES, make_user


def make_token(user, character_id: int, name: str = "Token Character") -> Token:
    """A django-esi token for the given character"""

    return Token.objects.create(
        user=user,
        character_id=character_id,
        character_name=name,
        character_owner_hash="hash",
        access_token="access",
        refresh_token="refresh",
    )


class TestConnectSource(TestCase):
    """connect_source"""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.manager = make_user("manager", "manage_access")
        cls.character_id = cls.manager.profile.main_character.character_id

    def test_connects_a_character_of_the_user(self):
        token = make_token(self.manager, self.character_id)

        source = connect_source(user=self.manager, token=token)

        self.assertEqual(source.corporation_id, 98000001)
        self.assertEqual(source.corporation_name, "Test Corp")
        self.assertEqual(source.token, token)
        self.assertEqual(source.connected_by, self.manager)
        self.assertIsNotNone(source.connected_at)
        self.assertTrue(source.token_ok)
        self.assertEqual(ContractSource.objects.count(), 1)

    def test_a_token_of_somebody_elses_character_is_refused(self):
        other = make_user("other", "manage_access")
        token = make_token(other, other.profile.main_character.character_id)

        with self.assertRaises(ValidationError):
            connect_source(user=self.manager, token=token)

        self.assertFalse(ContractSource.objects.exists())

    def test_connecting_again_replaces_the_source_and_clears_the_error(self):
        ContractSource.objects.create(
            corporation_id=1, corporation_name="Old", token_ok=False, last_error="boom"
        )
        token = make_token(self.manager, self.character_id)

        source = connect_source(user=self.manager, token=token)

        self.assertEqual(ContractSource.objects.count(), 1)
        self.assertEqual(source.corporation_name, "Test Corp")
        self.assertTrue(source.token_ok)
        self.assertEqual(source.last_error, "")


@override_settings(STORAGES=TEST_STORAGES)
class TestEsiConnectionBlock(TestCase):
    """The ESI connection block on the settings page"""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.manager = make_user("manager", "manage_access")
        cls.builder = make_user("builder", "builder_access")

    def test_connect_view_is_for_managers_only(self):
        url = reverse("evebuilders:connect_esi")

        self.assertEqual(self.client.get(url).status_code, 302)
        self.assertIn("login", self.client.get(url)["Location"])

        self.client.force_login(self.builder)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_not_connected(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:settings"))

        self.assertContains(response, "ESI connection")
        self.assertContains(response, "Not connected yet")
        self.assertContains(response, reverse("evebuilders:connect_esi"))

    def test_connected(self):
        ContractSource.objects.create(
            corporation_id=98000001,
            corporation_name="Test Corp",
            connected_by=self.manager,
            connected_at=timezone.now(),
        )
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:settings"))

        self.assertContains(response, "Test Corp")
        self.assertContains(response, "Reconnect")
        self.assertNotContains(response, "Not connected yet")
