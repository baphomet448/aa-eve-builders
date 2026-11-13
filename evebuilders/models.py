"""
App Models
Create your models in here
"""

# Django
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import translation
from django.utils.translation import gettext_lazy as _

# AA EVE Builders
from evebuilders.reasons import reason_text


class General(models.Model):
    """Meta model for app permissions"""

    class Meta:
        """Meta definitions"""

        managed = False
        default_permissions = ()
        permissions = (
            ("builder_access", "Can view and take corporate build orders"),
            ("manager_access", "Can manage the orders and the builders (manager)"),
            ("admin_access", "Can manage everything in the plugin (admin)"),
        )


class OrderSequence(models.Model):
    """Per-day counter used to build order numbers. Numbers are never reused."""

    date = models.DateField(unique=True)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        """Meta definitions"""

        default_permissions = ()

    def __str__(self) -> str:
        return f"{self.date}: {self.last_number}"


class Order(models.Model):
    """A build order"""

    class Kind(models.TextChoices):
        """Order kind (PRIVATE is reserved for later)"""

        CORPORATE = "CORPORATE", _("Corporate")
        PRIVATE = "PRIVATE", _("Private")

    class Status(models.TextChoices):
        """Order status"""

        NEW = "NEW", _("New")
        IN_PROGRESS = "IN_PROGRESS", _("In progress")
        DISTRIBUTED = "DISTRIBUTED", _("Distributed")
        COMPLETED = "COMPLETED", _("Done")
        CANCELLED = "CANCELLED", _("Cancelled")

    class Priority(models.TextChoices):
        """Order priority"""

        LOW = "LOW", _("Low")
        MEDIUM = "MEDIUM", _("Medium")
        HIGH = "HIGH", _("High")

    class AccessLevel(models.IntegerChoices):
        """Builder access level (integer so levels can be compared)"""

        BASE = 1, _("Base")
        MIDDLE = 2, _("Middle")
        SENIOR = 3, _("Senior")

    class ReceiverType(models.TextChoices):
        """Who receives the finished items (USER is reserved for later)"""

        CORPORATION = "CORPORATION", _("Corporation")
        USER = "USER", _("User")

    number = models.CharField(max_length=32, unique=True)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.CORPORATE)
    eve_type = models.ForeignKey(
        "eveuniverse.EveType", on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(
        max_digits=20, decimal_places=2, validators=[MinValueValidator(0)]
    )
    priority = models.CharField(
        max_length=8, choices=Priority.choices, default=Priority.MEDIUM
    )
    due_date = models.DateField()
    destination = models.CharField(max_length=255, blank=True, default="")
    receiver_type = models.CharField(
        max_length=16, choices=ReceiverType.choices, default=ReceiverType.CORPORATION
    )
    receiver_id = models.BigIntegerField(null=True, blank=True)
    receiver_name = models.CharField(max_length=255, blank=True, default="")
    note = models.TextField(blank=True, default="")
    access_level = models.PositiveSmallIntegerField(
        choices=AccessLevel.choices, default=AccessLevel.BASE
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.NEW, db_index=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Meta definitions"""

        default_permissions = ()
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.number


class OrderAssignment(models.Model):
    """
    A builder's share of an order.

    One row per (order, builder). Taking more later only raises ``taken``.
    ``credited`` is what has been accepted and counted. Items waiting for
    acceptance live on ContractRecord, so they are never overwritten here.
    The status is derived, not stored.
    """

    order = models.ForeignKey(
        Order, on_delete=models.PROTECT, related_name="assignments"
    )
    builder = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    taken = models.PositiveIntegerField(default=0)
    credited = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Meta definitions"""

        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["order", "builder"], name="evebuilders_unique_share"
            ),
            models.CheckConstraint(
                condition=Q(credited__lte=F("taken")),
                name="evebuilders_credited_lte_taken",
            ),
        ]

    @property
    def status(self) -> str:
        """Derived status: DISCARDED, IN_PROGRESS or COMPLETED"""

        if self.taken == 0:
            return "DISCARDED"
        if self.credited >= self.taken:
            return "COMPLETED"
        return "IN_PROGRESS"

    def __str__(self) -> str:
        return f"{self.order.number} / {self.builder_id}: {self.credited}/{self.taken}"


class OrderEvent(models.Model):
    """History entry. ``order`` is empty for global events (levels, token)."""

    class Kind(models.TextChoices):
        """Event kinds"""

        CREATED = "CREATED", _("Order created")
        UPDATED = "UPDATED", _("Order updated")
        CANCELLED = "CANCELLED", _("Order cancelled")
        TAKEN = "TAKEN", _("Taken")
        DISCARDED = "DISCARDED", _("Discarded")
        RELEASED = "RELEASED", _("Share released by manager")
        CONTRACT_FOUND = "CONTRACT_FOUND", _("Contract found")
        CONTRACT_INVALID = "CONTRACT_INVALID", _("Contract invalid")
        CONTRACT_CLOSED = "CONTRACT_CLOSED", _("Contract closed")
        CREDITED = "CREDITED", _("Credited")
        MANUAL_CREDIT = "MANUAL_CREDIT", _("Credited manually")
        LEVEL_CHANGED = "LEVEL_CHANGED", _("Builder level changed")
        TOKEN_ERROR = "TOKEN_ERROR", _("ESI token problem")

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="events",
    )
    assignment = models.ForeignKey(
        OrderAssignment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    kind = models.CharField(max_length=24, choices=Kind.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Meta definitions"""

        default_permissions = ()
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.kind} ({self.created_at:%Y-%m-%d %H:%M})"


class ContractRecord(models.Model):
    """A corporation contract that was matched (or looked like a match)"""

    class State(models.TextChoices):
        """Contract states"""

        OUTSTANDING = "OUTSTANDING", _("Waiting for acceptance")
        CREDITED = "CREDITED", _("Credited")
        INVALID = "INVALID", _("Invalid")
        CLOSED = "CLOSED", _("Closed without credit")

    contract_id = models.BigIntegerField(unique=True)
    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="contracts",
    )
    assignment = models.ForeignKey(
        OrderAssignment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="contracts",
    )
    title = models.CharField(max_length=255, blank=True, default="")
    issuer_character_id = models.BigIntegerField()
    acceptor_character_id = models.BigIntegerField(null=True, blank=True)
    acceptor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    quantity = models.PositiveIntegerField(default=0)
    price = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    esi_status = models.CharField(max_length=32, blank=True, default="")
    state = models.CharField(
        max_length=16, choices=State.choices, default=State.OUTSTANDING, db_index=True
    )
    reason = models.TextField(blank=True, default="")

    # Why the contract cannot be counted, as a code with parameters, so that the
    # text can be shown in the language of the reader. `reason` keeps the English
    # text: older records have only that, and it is the fallback.
    reason_code = models.CharField(max_length=40, blank=True, default="")
    reason_data = models.JSONField(blank=True, default=dict)

    issued_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Meta definitions"""

        default_permissions = ()
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.contract_id} ({self.state})"

    def save(self, *args, **kwargs):
        # No reason, no code: a contract that became valid has no problem left
        if not self.reason:
            self.reason_code = ""
            self.reason_data = {}

        super().save(*args, **kwargs)

    def reason_in(self, language: str) -> str:
        """The reason in a language. Older records have only the English text."""

        if not self.reason_code:
            return self.reason

        with translation.override(language):
            return reason_text(self.reason_code, self.reason_data)

    @property
    def reason_text(self) -> str:
        """The reason in the language of the current request"""

        return self.reason_in(translation.get_language() or "en")


class ContractSource(models.Model):
    """The single ESI source (corporation + token) used to read contracts"""

    corporation_id = models.BigIntegerField()
    corporation_name = models.CharField(max_length=255, blank=True, default="")
    token = models.ForeignKey(
        "esi.Token",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    connected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    connected_at = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    esi_expires_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    token_ok = models.BooleanField(default=True)

    class Meta:
        """Meta definitions"""

        default_permissions = ()

    def save(self, *args, **kwargs):
        """Keep this table to a single row"""

        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        """Return the single row or None if not connected yet"""

        return cls.objects.filter(pk=1).first()

    def __str__(self) -> str:
        return self.corporation_name or str(self.corporation_id)


class BuilderProfile(models.Model):
    """Builder access level. No row means BASE."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="evebuilders_profile",
    )
    level = models.PositiveSmallIntegerField(
        choices=Order.AccessLevel.choices, default=Order.AccessLevel.BASE
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Meta definitions"""

        default_permissions = ()

    def __str__(self) -> str:
        return f"{self.user_id}: {self.get_level_display()}"


class CatalogSync(models.Model):
    """
    State of the item catalog sync (single row).

    The end of a sync cannot be observed (eveuniverse fans the work out into
    many small tasks), so only the start is recorded.
    """

    started_at = models.DateTimeField(null=True, blank=True)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    category_ids = models.CharField(max_length=255, blank=True, default="")
    group_ids = models.CharField(max_length=255, blank=True, default="")
    last_error = models.TextField(blank=True, default="")

    class Meta:
        """Meta definitions"""

        default_permissions = ()

    def save(self, *args, **kwargs):
        """Keep this table to a single row"""

        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        """Return the single row, creating it if needed"""

        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self) -> str:
        return f"Catalog sync (started {self.started_at})"


class Destination(models.Model):
    """
    A place orders can be delivered to, added by a manager in the settings.

    Either an NPC station found through ESI, or a solar system (with the name
    of a structure typed by hand: player structures are not in the public ESI).
    The label is what the order form shows and what an order stores.
    """

    label = models.CharField(max_length=255, unique=True)
    system_id = models.PositiveIntegerField()
    system_name = models.CharField(max_length=100)
    station_id = models.PositiveIntegerField(null=True, blank=True)
    structure_name = models.CharField(max_length=200, blank=True, default="")
    created_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
        ordering = ["label"]

    def __str__(self) -> str:
        return self.label


class SolarSystem(models.Model):
    """
    The name of a solar system, copied from ESI. ESI cannot search systems by
    a part of the name, so the plugin keeps the names itself.
    """

    id = models.PositiveIntegerField(primary_key=True)
    name = models.CharField(max_length=100, db_index=True)

    class Meta:
        default_permissions = ()
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class DiscordConfig(models.Model):
    """
    The Discord webhooks, set by an administrator in the Django admin.

    A value that is set here wins over the same setting in local.py; a value
    that is left empty falls back to the setting. There is one row.
    """

    new_order_webhook_url = models.URLField(
        max_length=500,
        blank=True,
        default="",
        help_text="Webhook of the channel for new, changed and deleted orders.",
    )
    new_order_thread_id = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Thread ID, only if the webhook above posts into a thread.",
    )
    complete_webhook_url = models.URLField(
        max_length=500,
        blank=True,
        default="",
        help_text="Webhook of the channel for the reports about contracts and deliveries.",
    )
    complete_thread_id = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Thread ID, only if the webhook above posts into a thread.",
    )
    review_webhook_url = models.URLField(
        max_length=500,
        blank=True,
        default="",
        help_text="Webhook of the third channel, for the orders on review (optional).",
    )
    review_thread_id = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Thread ID, only if the webhook above posts into a thread.",
    )
    routes = models.JSONField(
        blank=True,
        default=dict,
        help_text=(
            "Which kind of message goes to which channel, and whether it mentions "
            "everyone. Set in the settings of the plugin."
        ),
    )
    notify_taken = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Announce that a builder took a part of an order. "
            "Unknown means: use the setting from local.py (default: yes)."
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Discord settings"
        verbose_name_plural = "Discord settings"

    def __str__(self) -> str:
        return "Discord settings"
