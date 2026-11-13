"""View tests"""

# Standard Library
from itertools import count
from unittest.mock import patch

# Django
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.messages import constants, get_messages
from django.test import Client, TestCase, override_settings
from django.urls import reverse

# Alliance Auth
from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter

# AA EVE Builders
from evebuilders.catalog import SyncResult

User = get_user_model()
_character_ids = count(90000001)

# The test project uses a manifest static files storage that needs collectstatic.
# A plain storage is enough for rendering pages in tests.
TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def make_user(username: str, *codenames: str):
    """
    A user with a main character and the given evebuilders permissions.

    Alliance Auth sends users without a main character to the dashboard,
    so every test user needs one.
    """

    user = User.objects.create_user(username)
    character = EveCharacter.objects.create(
        character_id=next(_character_ids),
        character_name=f"{username} character",
        corporation_id=98000001,
        corporation_name="Test Corp",
        corporation_ticker="TST",
    )
    CharacterOwnership.objects.create(
        character=character, user=user, owner_hash=f"hash-{username}"
    )
    user.profile.main_character = character
    user.profile.save()

    for codename in codenames:
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="evebuilders", codename=codename
            )
        )

    return User.objects.get(pk=user.pk)  # fresh instance: drops the permission cache


@override_settings(STORAGES=TEST_STORAGES)
class TestSettingsPage(TestCase):
    """The settings page is for managers only"""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.manager = make_user("manager", "admin_access")
        cls.builder = make_user("builder", "builder_access")

    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(reverse("evebuilders:settings"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_builder_without_admin_access_is_refused(self):
        self.client.force_login(self.builder)

        response = self.client.get(reverse("evebuilders:settings"))

        self.assertEqual(response.status_code, 302)

    def test_manager_sees_the_page(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Update catalog")
        self.assertEqual(len(response.context["rows"]), 10)

    def test_tabs_are_only_shown_to_managers(self):
        settings_url = reverse("evebuilders:settings")

        self.client.force_login(self.manager)
        manager_page = self.client.get(reverse("evebuilders:orders"))
        self.client.force_login(self.builder)
        builder_page = self.client.get(reverse("evebuilders:orders"))

        self.assertContains(manager_page, settings_url)
        self.assertNotContains(builder_page, settings_url)


class TestStartSync(TestCase):
    """The update button"""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.manager = make_user("manager", "admin_access")
        cls.builder = make_user("builder", "builder_access")

    def test_get_is_not_allowed(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:sync_catalog"))

        self.assertEqual(response.status_code, 405)

    @patch("evebuilders.views.start_catalog_sync")
    def test_builder_cannot_start_a_sync(self, mock_start):
        self.client.force_login(self.builder)

        response = self.client.post(reverse("evebuilders:sync_catalog"))

        self.assertEqual(response.status_code, 302)
        mock_start.assert_not_called()

    @patch("evebuilders.views.start_catalog_sync")
    def test_manager_starts_a_sync_and_is_sent_back(self, mock_start):
        mock_start.return_value = SyncResult.STARTED
        self.client.force_login(self.manager)

        response = self.client.post(reverse("evebuilders:sync_catalog"))

        self.assertRedirects(
            response, reverse("evebuilders:settings"), fetch_redirect_response=False
        )
        mock_start.assert_called_once()
        self.assertEqual(mock_start.call_args.kwargs["user"].pk, self.manager.pk)

    @patch("evebuilders.views.start_catalog_sync")
    def test_each_outcome_gives_one_message(self, mock_start):
        expected = {
            SyncResult.STARTED: constants.SUCCESS,
            SyncResult.TOO_SOON: constants.WARNING,
            SyncResult.ESI_OFFLINE: constants.ERROR,
            SyncResult.NOTHING_TO_LOAD: constants.WARNING,
            SyncResult.FAILED: constants.ERROR,
        }

        for result, level in expected.items():
            with self.subTest(result=result):
                mock_start.return_value = result
                client = Client()  # fresh client: no messages left over from before
                client.force_login(self.manager)

                response = client.post(reverse("evebuilders:sync_catalog"))

                levels = [m.level for m in get_messages(response.wsgi_request)]
                self.assertEqual(levels, [level])
