"""The roles of the plugin: admin, manager and builder"""

# Django
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group, Permission
from django.test import TestCase, override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.permissions import (
    NO_ROLE,
    ROLE_ADMIN,
    ROLE_BUILDER,
    ROLE_MANAGER,
    has_any_access,
    is_admin,
    is_manager,
    role_of,
)
from evebuilders.templatetags.evebuilders_extras import (
    can_access,
    can_administer,
    can_manage,
)
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES

User = get_user_model()


def permission(codename: str) -> Permission:
    """A permission of the plugin"""

    return Permission.objects.get(
        content_type__app_label="evebuilders", codename=codename
    )


def user_with(*codenames: str, **fields) -> User:
    """A user that has the permissions given to him himself"""

    user = User.objects.create_user(username=f"user-{User.objects.count()}", **fields)
    for codename in codenames:
        user.user_permissions.add(permission(codename))

    return User.objects.get(pk=user.pk)


class TestThePermissions(TestCase):
    """What exists"""

    def test_the_three_permissions_exist_and_the_old_one_is_gone(self):
        codenames = set(
            Permission.objects.filter(
                content_type__app_label="evebuilders", content_type__model="general"
            ).values_list("codename", flat=True)
        )

        self.assertEqual(
            codenames, {"builder_access", "manager_access", "admin_access"}
        )


class TestTheRoles(TestCase):
    """The role of a user"""

    def test_nobody_without_a_permission_has_a_role(self):
        user = user_with()

        self.assertEqual(role_of(user), NO_ROLE)
        self.assertFalse(has_any_access(user))

    def test_a_permission_given_to_the_user(self):
        cases = {
            "builder_access": ROLE_BUILDER,
            "manager_access": ROLE_MANAGER,
            "admin_access": ROLE_ADMIN,
        }

        for codename, role in cases.items():
            with self.subTest(codename=codename):
                self.assertEqual(role_of(user_with(codename)), role)

    def test_a_permission_of_a_group(self):
        group = Group.objects.create(name="Officers")
        group.permissions.add(permission("manager_access"))
        user = user_with()
        user.groups.add(group)

        self.assertEqual(role_of(User.objects.get(pk=user.pk)), ROLE_MANAGER)

    def test_a_permission_of_the_state(self):
        user = user_with()
        state = user.profile.state
        # The state has its own model of permissions (not the one of Django)
        of_the_state = type(state).permissions.field.related_model.objects.get(
            content_type__app_label="evebuilders", codename="builder_access"
        )
        state.permissions.add(of_the_state)

        self.assertEqual(role_of(User.objects.get(pk=user.pk)), ROLE_BUILDER)

    def test_the_highest_role_wins(self):
        self.assertEqual(
            role_of(user_with("builder_access", "manager_access")), ROLE_MANAGER
        )
        self.assertEqual(
            role_of(user_with("builder_access", "manager_access", "admin_access")),
            ROLE_ADMIN,
        )

    def test_a_superuser_has_no_role_by_being_one(self):
        user = User.objects.create_superuser("root", "root@example.com", "password")

        self.assertTrue(user.has_perm("evebuilders.admin_access"))  # Django says so
        self.assertEqual(role_of(user), NO_ROLE)
        self.assertFalse(is_admin(user))
        self.assertFalse(has_any_access(user))

    def test_a_superuser_gets_a_role_when_it_is_given_to_him(self):
        user = User.objects.create_superuser("root", "root@example.com", "password")
        user.user_permissions.add(permission("admin_access"))

        self.assertEqual(role_of(User.objects.get(pk=user.pk)), ROLE_ADMIN)

    def test_an_inactive_user_has_no_role(self):
        user = user_with("admin_access", is_active=False)

        self.assertEqual(role_of(user), NO_ROLE)

    def test_an_anonymous_user_has_no_role(self):
        self.assertEqual(role_of(AnonymousUser()), NO_ROLE)

    def test_what_each_role_may_do(self):
        builder = user_with("builder_access")
        manager = user_with("manager_access")
        admin = user_with("admin_access")

        self.assertEqual(
            [has_any_access(u) for u in (builder, manager, admin)], [True] * 3
        )
        self.assertEqual(
            [is_manager(u) for u in (builder, manager, admin)], [False, True, True]
        )
        self.assertEqual(
            [is_admin(u) for u in (builder, manager, admin)], [False, False, True]
        )

    def test_the_filters_of_the_templates_say_the_same(self):
        manager = user_with("manager_access")

        self.assertTrue(can_access(manager))
        self.assertTrue(can_manage(manager))
        self.assertFalse(can_administer(manager))


@override_settings(STORAGES=TEST_STORAGES)
class TestThePages(ViewsTestCase):
    """The pages follow the roles"""

    def _status(self, user, name) -> int:
        self.client.force_login(user)

        return self.client.get(reverse(name)).status_code

    def test_a_builder_may_not_enter_the_management(self):
        self.assertEqual(self._status(self.builder, "evebuilders:orders"), 200)
        self.assertEqual(self._status(self.builder, "evebuilders:management"), 302)

    def test_a_manager_enters_the_management(self):
        self.builder.user_permissions.add(permission("manager_access"))

        self.assertEqual(self._status(self.builder, "evebuilders:management"), 200)

    def test_an_admin_enters_the_management(self):
        self.assertEqual(self._status(self.manager, "evebuilders:management"), 200)

    def test_a_superuser_without_a_role_enters_nothing(self):
        root = User.objects.create_superuser("root", "root@example.com", "password")

        for name in ("evebuilders:orders", "evebuilders:management"):
            with self.subTest(page=name):
                self.assertEqual(self._status(root, name), 302)
