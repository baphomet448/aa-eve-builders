"""Model and permission tests"""

# Standard Library
import datetime
from decimal import Decimal

# Third Party
# EVE Universe
from eveuniverse.models import EveCategory, EveGroup, EveType

# Django
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import IntegrityError, transaction
from django.db.models import F
from django.test import TestCase

# AA EVE Builders
from evebuilders import app_settings
from evebuilders.models import (
    BuilderProfile,
    CatalogSync,
    ContractRecord,
    ContractSource,
    Order,
    OrderAssignment,
)
from evebuilders.permissions import has_any_access

User = get_user_model()


class OrderTestCase(TestCase):
    """Base class: one item type, one builder and one order"""

    @classmethod
    def setUpTestData(cls) -> None:
        category = EveCategory.objects.create(id=6, name="Ship", published=True)
        group = EveGroup.objects.create(
            id=25, name="Frigate", eve_category=category, published=True
        )
        cls.eve_type = EveType.objects.create(
            id=597, name="Punisher", eve_group=group, published=True
        )
        cls.builder = User.objects.create_user("builder1")
        cls.order = Order.objects.create(
            number="N20261018-1",
            eve_type=cls.eve_type,
            quantity=1000,
            unit_price=Decimal("1000000.00"),
            due_date=datetime.date(2026, 12, 1),
            created_by=cls.builder,
        )


class TestOrderDefaults(OrderTestCase):
    """Order defaults"""

    def test_defaults(self):
        self.assertEqual(self.order.status, Order.Status.NEW)
        self.assertEqual(self.order.kind, Order.Kind.CORPORATE)
        self.assertEqual(self.order.access_level, Order.AccessLevel.BASE)
        self.assertEqual(self.order.receiver_type, Order.ReceiverType.CORPORATION)
        self.assertEqual(self.order.priority, Order.Priority.MEDIUM)


class TestOrderAssignment(OrderTestCase):
    """Builder share: derived status and constraints"""

    def test_status_discarded_when_nothing_taken(self):
        share = OrderAssignment(order=self.order, builder=self.builder, taken=0)
        self.assertEqual(share.status, "DISCARDED")

    def test_status_in_progress(self):
        share = OrderAssignment(
            order=self.order, builder=self.builder, taken=5, credited=0
        )
        self.assertEqual(share.status, "IN_PROGRESS")
        share.credited = 4
        self.assertEqual(share.status, "IN_PROGRESS")

    def test_status_completed(self):
        share = OrderAssignment(
            order=self.order, builder=self.builder, taken=5, credited=5
        )
        self.assertEqual(share.status, "COMPLETED")

    def test_credited_cannot_exceed_taken(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OrderAssignment.objects.create(
                    order=self.order, builder=self.builder, taken=5, credited=6
                )

    def test_one_share_per_builder_and_order(self):
        OrderAssignment.objects.create(order=self.order, builder=self.builder, taken=5)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OrderAssignment.objects.create(
                    order=self.order, builder=self.builder, taken=3
                )

    def test_taking_more_does_not_touch_pending_contract(self):
        """
        Model-level invariant behind the "second batch" bug: taking more only
        raises ``taken``; a contract waiting for acceptance stays as it was.
        The full service-level regression test comes with step 3.
        """

        share = OrderAssignment.objects.create(
            order=self.order, builder=self.builder, taken=500
        )
        contract = ContractRecord.objects.create(
            contract_id=1001,
            order=self.order,
            assignment=share,
            issuer_character_id=1,
            quantity=500,
            state=ContractRecord.State.OUTSTANDING,
        )

        OrderAssignment.objects.filter(pk=share.pk).update(taken=F("taken") + 500)
        share.refresh_from_db()
        contract.refresh_from_db()

        self.assertEqual(share.taken, 1000)
        self.assertEqual(share.credited, 0)
        self.assertEqual(share.status, "IN_PROGRESS")
        self.assertEqual(contract.state, ContractRecord.State.OUTSTANDING)
        self.assertEqual(contract.quantity, 500)


class TestContractSource(TestCase):
    """The contract source table keeps a single row"""

    def test_single_row(self):
        ContractSource.objects.create(corporation_id=1)
        ContractSource(corporation_id=2).save()

        self.assertEqual(ContractSource.objects.count(), 1)
        self.assertEqual(ContractSource.get_solo().corporation_id, 2)

    def test_get_solo_without_row(self):
        self.assertIsNone(ContractSource.get_solo())


class TestBuilderProfile(TestCase):
    """Builder level"""

    def test_default_level_is_base(self):
        user = User.objects.create_user("builder2")
        profile = BuilderProfile.objects.create(user=user)
        self.assertEqual(profile.level, Order.AccessLevel.BASE)


class TestPermissions(TestCase):
    """Who may see the plugin"""

    @staticmethod
    def _user_with(codename=None):
        user = User.objects.create_user(f"user_{codename}")
        if codename:
            user.user_permissions.add(
                Permission.objects.get(
                    content_type__app_label="evebuilders", codename=codename
                )
            )
            user = User.objects.get(pk=user.pk)  # drop the permission cache
        return user

    def test_no_permissions(self):
        self.assertFalse(has_any_access(self._user_with(None)))

    def test_builder_access(self):
        self.assertTrue(has_any_access(self._user_with("builder_access")))

    def test_admin_access(self):
        self.assertTrue(has_any_access(self._user_with("admin_access")))


class TestCatalogSync(TestCase):
    """Catalog sync state keeps a single row"""

    def test_get_solo_creates_single_row(self):
        first = CatalogSync.get_solo()
        second = CatalogSync.get_solo()

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(CatalogSync.objects.count(), 1)
        self.assertIsNone(first.started_at)


class TestAppSettings(TestCase):
    """Catalog settings have the agreed defaults"""

    def test_defaults(self):
        self.assertEqual(
            app_settings.EVEBUILDERS_CATALOG_CATEGORY_IDS,
            [4, 6, 7, 8, 18, 22, 32, 65, 66, 87],
        )
        self.assertEqual(app_settings.EVEBUILDERS_CATALOG_GROUP_IDS, [])
        self.assertEqual(app_settings.EVEBUILDERS_CATALOG_MIN_INTERVAL_MINUTES, 15)
