"""Roles on the page of the builder levels: who is what, and who makes managers"""

# Django
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.levels import level_rows, set_manager_role
from evebuilders.messages import display_name
from evebuilders.models import OrderEvent
from evebuilders.permissions import ROLE_ADMIN, ROLE_BUILDER, ROLE_MANAGER, role_of
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES, make_user

User = get_user_model()


def manager_permission() -> Permission:
    """The permission of a manager"""

    return Permission.objects.get(
        content_type__app_label="evebuilders", codename="manager_access"
    )


def fresh(user):
    """The user as the database has him now"""

    return User.objects.get(pk=user.pk)


@override_settings(STORAGES=TEST_STORAGES)
class RoleManagementTestCase(ViewsTestCase):
    """self.manager is an admin, self.officer a manager, self.target a builder"""

    def setUp(self):
        self.builder.user_permissions.add(manager_permission())
        self.officer = fresh(self.builder)
        self.target = make_user("target", "builder_access")

    def _rm_row(self, user) -> dict:
        return next(row for row in level_rows() if row["user"].pk == user.pk)

    def _rm_make(self, actor, user, manager):
        self.client.force_login(actor)

        return self.client.post(
            reverse("evebuilders:set_manager", args=[user.pk]),
            {"manager": "1" if manager else "0"},
        )

    def _rm_page(self, actor):
        self.client.force_login(actor)

        return self.client.get(reverse("evebuilders:builder_levels"))

    @staticmethod
    def _rm_messages(response) -> list[str]:
        return [str(message) for message in get_messages(response.wsgi_request)]


class TestRolesInTheRows(RoleManagementTestCase):
    """What the rows of the page say"""

    def test_every_row_has_its_role_and_rank(self):
        self.assertEqual(self._rm_row(self.manager)["role"], ROLE_ADMIN)
        self.assertEqual(self._rm_row(self.officer)["role"], ROLE_MANAGER)
        self.assertEqual(self._rm_row(self.target)["role"], ROLE_BUILDER)
        self.assertEqual(
            [
                self._rm_row(u)["role_rank"]
                for u in (self.manager, self.officer, self.target)
            ],
            [3, 2, 1],
        )

    def test_a_manager_given_to_the_user_himself_is_marked(self):
        row = self._rm_row(self.officer)

        self.assertTrue(row["manager_direct"])
        self.assertEqual(row["manager_via"], "")

    def test_a_manager_through_a_group_says_which(self):
        group = Group.objects.create(name="Officers")
        group.permissions.add(manager_permission())
        self.target.groups.add(group)

        row = self._rm_row(self.target)

        self.assertEqual(row["role"], ROLE_MANAGER)
        self.assertFalse(row["manager_direct"])
        self.assertEqual(row["manager_via"], "Officers")


class TestSetManagerRole(RoleManagementTestCase):
    """Making and unmaking a manager"""

    def test_a_builder_becomes_a_manager_and_the_history_says_so(self):
        changed = set_manager_role(actor=self.manager, user=self.target, manager=True)

        self.assertTrue(changed)
        self.assertEqual(role_of(fresh(self.target)), ROLE_MANAGER)
        event = OrderEvent.objects.get(kind=OrderEvent.Kind.ROLE_CHANGED)
        self.assertEqual(
            event.description,
            f"Role of {display_name(self.target)}: Builder -> Manager",
        )
        self.assertEqual(event.actor, self.manager)

    def test_a_manager_stays_a_manager_without_a_new_event(self):
        set_manager_role(actor=self.manager, user=self.target, manager=True)

        again = set_manager_role(actor=self.manager, user=self.target, manager=True)

        self.assertFalse(again)
        self.assertEqual(OrderEvent.objects.filter(kind="ROLE_CHANGED").count(), 1)

    def test_the_role_is_taken_away(self):
        set_manager_role(actor=self.manager, user=self.target, manager=True)

        changed = set_manager_role(actor=self.manager, user=self.target, manager=False)

        self.assertTrue(changed)
        self.assertEqual(role_of(fresh(self.target)), ROLE_BUILDER)
        last = OrderEvent.objects.filter(kind="ROLE_CHANGED").order_by("-id").first()
        self.assertTrue(last.description.endswith("Manager -> Builder"))

    def test_a_role_from_a_group_is_not_taken_away_here(self):
        group = Group.objects.create(name="Officers")
        group.permissions.add(manager_permission())
        self.target.groups.add(group)

        with self.assertRaises(ValidationError) as caught:
            set_manager_role(actor=self.manager, user=self.target, manager=False)

        self.assertIn("Officers", caught.exception.messages[0])
        self.assertEqual(role_of(fresh(self.target)), ROLE_MANAGER)

    def test_taking_away_what_is_not_there_changes_nothing(self):
        changed = set_manager_role(actor=self.manager, user=self.target, manager=False)

        self.assertFalse(changed)
        self.assertFalse(OrderEvent.objects.filter(kind="ROLE_CHANGED").exists())

    def test_an_admin_cannot_be_changed_here(self):
        with self.assertRaises(ValidationError):
            set_manager_role(actor=self.manager, user=self.manager, manager=False)


class TestTheView(RoleManagementTestCase):
    """Who may do it"""

    def test_an_admin_makes_a_manager(self):
        response = self._rm_make(self.manager, self.target, True)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(role_of(fresh(self.target)), ROLE_MANAGER)
        self.assertIn(
            f"{display_name(self.target)} is now a manager.",
            self._rm_messages(response),
        )

    def test_a_manager_may_not(self):
        response = self._rm_make(self.officer, self.target, True)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/account/login/"))
        self.assertEqual(role_of(fresh(self.target)), ROLE_BUILDER)

    def test_a_builder_may_not(self):
        response = self._rm_make(self.target, self.target, True)

        self.assertTrue(response["Location"].startswith("/account/login/"))
        self.assertEqual(role_of(fresh(self.target)), ROLE_BUILDER)

    def test_somebody_without_a_role_is_not_found(self):
        nobody = User.objects.create_user("nobody")

        response = self._rm_make(self.manager, nobody, True)

        self.assertEqual(response.status_code, 404)

    def test_an_admin_is_told_that_an_admin_is_made_elsewhere(self):
        response = self._rm_make(self.manager, self.manager, False)

        self.assertIn(
            "The role of an admin is set in the admin site of Auth.",
            self._rm_messages(response),
        )


class TestThePage(RoleManagementTestCase):
    """What the page shows"""

    def test_an_admin_sees_the_buttons(self):
        response = self._rm_page(self.manager)

        self.assertContains(response, "Make manager")
        self.assertContains(response, "Remove manager")
        self.assertContains(
            response, reverse("evebuilders:set_manager", args=[self.target.pk])
        )

    def test_a_manager_sees_the_roles_but_no_buttons(self):
        response = self._rm_page(self.officer)

        self.assertNotContains(response, "Make manager")
        self.assertNotContains(response, "Remove manager")
        self.assertContains(response, 'class="badge bg-info">Admin</span>')
        self.assertContains(response, 'class="badge bg-primary">Manager</span>')

    def test_a_role_from_a_group_has_the_group_and_no_button(self):
        group = Group.objects.create(name="Officers")
        group.permissions.add(manager_permission())
        self.target.groups.add(group)

        response = self._rm_page(self.manager)

        self.assertContains(response, "(Officers)")
        self.assertNotContains(
            response, reverse("evebuilders:set_manager", args=[self.target.pk])
        )

    def test_the_rows_carry_the_role_for_the_filter(self):
        response = self._rm_page(self.manager)

        self.assertContains(response, 'data-filter-eq="role"')
        for role in ("admin", "manager", "builder"):
            with self.subTest(role=role):
                self.assertContains(response, f'data-role="{role}"')

    def test_the_column_is_called_role(self):
        response = self._rm_page(self.manager)
        head = response.content.decode().split("<thead>")[1].split("</thead>")[0]

        self.assertIn("Role", head)
        self.assertNotIn("Access", head)

    def test_the_level_and_the_button_are_in_one_row(self):
        response = self._rm_page(self.manager)
        content = response.content.decode()
        action = reverse("evebuilders:set_level", args=[self.target.pk])

        start = content.index(f'action="{action}"')
        form = content[start : content.index("</form>", start)]

        self.assertIn('class="badge', form)
        self.assertIn('name="level"', form)
        self.assertIn("align-items-center", content[start - 120 : start + 200])

    def test_the_change_of_a_role_is_in_the_history(self):
        set_manager_role(actor=self.manager, user=self.target, manager=True)
        self.client.force_login(self.manager)

        response = self.client.get(reverse("evebuilders:management_history"))

        self.assertContains(response, "Builder role changed")
