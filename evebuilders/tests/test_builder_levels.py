"""Builder levels: who is listed, changing a level, the pages"""

# Django
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.messages import constants, get_messages
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

# Alliance Auth
from allianceauth.authentication.models import State

# AA EVE Builders
from evebuilders.levels import builder_users, level_rows, set_builder_level
from evebuilders.messages import display_name
from evebuilders.models import BuilderProfile, Order, OrderEvent
from evebuilders.orders import visible_orders
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES, make_user

User = get_user_model()


def listed(user) -> bool:
    return builder_users().filter(pk=user.pk).exists()


class TestBuilderUsers(TestCase):
    """builder_users"""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.manager = make_user("manager", "manage_access")
        cls.builder = make_user("builder", "builder_access")
        cls.nobody = make_user("nobody")
        cls.permission = Permission.objects.get(codename="builder_access")

    def test_users_with_their_own_permission(self):
        self.assertTrue(listed(self.manager))
        self.assertTrue(listed(self.builder))
        self.assertFalse(listed(self.nobody))

    def test_permission_through_a_group(self):
        user = make_user("grouped")
        group = Group.objects.create(name="Builders")
        group.permissions.add(self.permission)
        user.groups.add(group)

        self.assertTrue(listed(user))

    def test_permission_through_the_state(self):
        user = make_user("stated")
        state = State.objects.create(name="Test state", priority=1000)
        state.permissions.add(self.permission.pk)
        user.profile.state = state
        # Only the state is saved: a plain save() makes Auth work out the state anew
        user.profile.save(update_fields=["state"])

        user.profile.refresh_from_db()
        self.assertEqual(user.profile.state, state)  # the state must have stuck
        self.assertTrue(listed(user))

    def test_superusers_are_listed(self):
        root = User.objects.create_superuser("root", "root@example.com", "password")

        self.assertTrue(listed(root))

    def test_inactive_users_are_not_listed(self):
        User.objects.filter(pk=self.builder.pk).update(is_active=False)

        self.assertFalse(listed(self.builder))

    def test_every_user_is_listed_once(self):
        group = Group.objects.create(name="Builders")
        group.permissions.add(self.permission)
        self.builder.groups.add(group)  # a second way to the same permission

        self.assertEqual(builder_users().filter(pk=self.builder.pk).count(), 1)


class TestSetBuilderLevel(ViewsTestCase):
    """set_builder_level"""

    def test_changes_the_level_and_writes_an_event(self):
        changed = set_builder_level(
            actor=self.manager, user=self.builder, level=Order.AccessLevel.MIDDLE
        )

        self.assertTrue(changed)
        self.assertEqual(
            BuilderProfile.objects.get(user=self.builder).level,
            Order.AccessLevel.MIDDLE,
        )
        event = OrderEvent.objects.get(kind=OrderEvent.Kind.LEVEL_CHANGED)
        self.assertEqual(event.actor, self.manager)
        self.assertIsNone(event.order)
        self.assertIn("Base", event.description)
        self.assertIn("Middle", event.description)

    def test_the_same_level_changes_nothing(self):
        set_builder_level(
            actor=self.manager, user=self.builder, level=Order.AccessLevel.MIDDLE
        )

        changed = set_builder_level(
            actor=self.manager, user=self.builder, level=Order.AccessLevel.MIDDLE
        )

        self.assertFalse(changed)
        self.assertEqual(
            OrderEvent.objects.filter(kind=OrderEvent.Kind.LEVEL_CHANGED).count(), 1
        )

    def test_base_is_the_default_so_setting_it_changes_nothing(self):
        changed = set_builder_level(
            actor=self.manager, user=self.builder, level=Order.AccessLevel.BASE
        )

        self.assertFalse(changed)
        self.assertFalse(BuilderProfile.objects.filter(user=self.builder).exists())

    def test_there_is_one_profile_per_user(self):
        set_builder_level(
            actor=self.manager, user=self.builder, level=Order.AccessLevel.MIDDLE
        )
        set_builder_level(
            actor=self.manager, user=self.builder, level=Order.AccessLevel.SENIOR
        )

        self.assertEqual(BuilderProfile.objects.filter(user=self.builder).count(), 1)
        self.assertEqual(
            BuilderProfile.objects.get(user=self.builder).level,
            Order.AccessLevel.SENIOR,
        )
        self.assertEqual(
            OrderEvent.objects.filter(kind=OrderEvent.Kind.LEVEL_CHANGED).count(), 2
        )

    def test_an_unknown_level_is_refused(self):
        with self.assertRaises(ValidationError):
            set_builder_level(actor=self.manager, user=self.builder, level=9)

        self.assertFalse(BuilderProfile.objects.exists())

    def test_the_new_level_unlocks_orders(self):
        self.assertNotIn(self.middle.pk, [o.pk for o in visible_orders(self.builder)])

        set_builder_level(
            actor=self.manager, user=self.builder, level=Order.AccessLevel.MIDDLE
        )

        self.assertIn(self.middle.pk, [o.pk for o in visible_orders(self.builder)])


class TestLevelRows(ViewsTestCase):
    """level_rows"""

    def _rows(self):
        return {row["user"].pk: row for row in level_rows()}

    def test_rows_have_the_level_and_the_role(self):
        rows = self._rows()

        self.assertEqual(rows[self.builder.pk]["level"], Order.AccessLevel.BASE)
        self.assertFalse(rows[self.builder.pk]["is_manager"])
        self.assertTrue(rows[self.manager.pk]["is_manager"])
        self.assertEqual(
            rows[self.builder.pk]["name"], display_name(self.builder)
        )

    def test_rows_show_the_level_that_was_set(self):
        set_builder_level(
            actor=self.manager, user=self.builder, level=Order.AccessLevel.SENIOR
        )

        self.assertEqual(self._rows()[self.builder.pk]["level"], Order.AccessLevel.SENIOR)


@override_settings(STORAGES=TEST_STORAGES)
class TestBuilderLevelsPages(ViewsTestCase):
    """The pages"""

    def _post(self, user, level, who=None):
        client = Client()  # fresh client: no messages left over from before
        client.force_login(who or self.manager)

        return client.post(
            reverse("evebuilders:set_level", args=[user.pk]), {"level": level}
        )

    @staticmethod
    def _levels(response):
        return [m.level for m in get_messages(response.wsgi_request)]

    def test_anonymous_and_builders_are_sent_away(self):
        page = reverse("evebuilders:builder_levels")
        set_url = reverse("evebuilders:set_level", args=[self.builder.pk])

        self.assertEqual(self.client.get(page).status_code, 302)
        self.assertEqual(self.client.post(set_url, {"level": "2"}).status_code, 302)

        self.client.force_login(self.builder)
        self.assertEqual(self.client.get(page).status_code, 302)
        self.assertEqual(self.client.post(set_url, {"level": "2"}).status_code, 302)
        self.assertFalse(BuilderProfile.objects.exists())

    def test_the_manager_sees_the_builders(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:builder_levels"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, display_name(self.builder))
        self.assertContains(response, display_name(self.other))
        self.assertContains(
            response, reverse("evebuilders:set_level", args=[self.builder.pk])
        )

    def test_the_settings_page_has_the_tabs(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:settings"))

        self.assertContains(response, reverse("evebuilders:builder_levels"))

    def test_changing_a_level(self):
        response = self._post(self.builder, "2")

        self.assertRedirects(
            response,
            reverse("evebuilders:builder_levels"),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            BuilderProfile.objects.get(user=self.builder).level,
            Order.AccessLevel.MIDDLE,
        )
        self.assertEqual(self._levels(response), [constants.SUCCESS])

    def test_the_same_level_is_only_an_info(self):
        response = self._post(self.builder, "1")

        self.assertEqual(self._levels(response), [constants.INFO])
        self.assertFalse(BuilderProfile.objects.exists())

    def test_a_bad_level_is_an_error(self):
        for value in ("9", "abc", ""):
            with self.subTest(value=value):
                response = self._post(self.builder, value)

                self.assertEqual(self._levels(response), [constants.ERROR])

        self.assertFalse(BuilderProfile.objects.exists())

    def test_someone_without_access_is_not_found(self):
        nobody = make_user("nobody")

        response = self._post(nobody, "2")

        self.assertEqual(response.status_code, 404)

    def test_get_is_not_allowed(self):
        self.client.force_login(self.manager)

        response = self.client.get(
            reverse("evebuilders:set_level", args=[self.builder.pk])
        )

        self.assertEqual(response.status_code, 405)