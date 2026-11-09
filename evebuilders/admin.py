"""Admin models"""

# Django
from django import forms
from django.contrib import admin

# AA EVE Builders
from evebuilders.models import (
    BuilderProfile,
    CatalogSync,
    ContractRecord,
    ContractSource,
    DiscordConfig,
    Order,
    OrderAssignment,
    OrderEvent,
    OrderSequence,
)


class OrderAssignmentInline(admin.TabularInline):
    """Builder shares shown inside the order page"""

    model = OrderAssignment
    extra = 0
    raw_id_fields = ("builder",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Orders"""

    list_display = (
        "number",
        "eve_type",
        "quantity",
        "unit_price",
        "status",
        "access_level",
        "priority",
        "due_date",
        "created_at",
    )
    list_filter = ("status", "kind", "priority", "access_level")
    search_fields = ("number", "eve_type__name")
    raw_id_fields = ("eve_type", "created_by", "updated_by")
    readonly_fields = ("created_at", "updated_at")
    inlines = [OrderAssignmentInline]


@admin.register(OrderAssignment)
class OrderAssignmentAdmin(admin.ModelAdmin):
    """Builder shares"""

    list_display = ("order", "builder", "taken", "credited", "status", "updated_at")
    search_fields = ("order__number",)
    raw_id_fields = ("order", "builder")
    readonly_fields = ("created_at", "updated_at")


@admin.register(OrderEvent)
class OrderEventAdmin(admin.ModelAdmin):
    """Order history"""

    list_display = ("created_at", "kind", "order", "actor", "description")
    list_filter = ("kind",)
    search_fields = ("order__number", "description")
    raw_id_fields = ("order", "assignment", "actor")
    readonly_fields = ("created_at",)


@admin.register(ContractRecord)
class ContractRecordAdmin(admin.ModelAdmin):
    """Matched corporation contracts"""

    list_display = (
        "contract_id",
        "order",
        "state",
        "quantity",
        "price",
        "esi_status",
        "issuer_character_id",
        "acceptor_character_id",
        "updated_at",
    )
    list_filter = ("state", "esi_status")
    search_fields = ("contract_id", "title", "order__number")
    raw_id_fields = ("order", "assignment", "acceptor_user")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ContractSource)
class ContractSourceAdmin(admin.ModelAdmin):
    """The single ESI source for corporation contracts"""

    list_display = (
        "corporation_name",
        "corporation_id",
        "token_ok",
        "last_success_at",
        "last_error",
    )
    raw_id_fields = ("token", "connected_by")

    def has_add_permission(self, request):
        """Only one row is allowed"""

        return not ContractSource.objects.exists()


@admin.register(BuilderProfile)
class BuilderProfileAdmin(admin.ModelAdmin):
    """Builder access levels"""

    list_display = ("user", "level", "updated_at")
    list_filter = ("level",)
    raw_id_fields = ("user",)


@admin.register(OrderSequence)
class OrderSequenceAdmin(admin.ModelAdmin):
    """Per-day order counters"""

    list_display = ("date", "last_number")


@admin.register(CatalogSync)
class CatalogSyncAdmin(admin.ModelAdmin):
    """Item catalog sync state (single row)"""

    list_display = (
        "started_at",
        "started_by",
        "category_ids",
        "group_ids",
        "last_error",
    )
    raw_id_fields = ("started_by",)

    def has_add_permission(self, request):
        """Only one row is allowed"""

        return not CatalogSync.objects.exists()


class DiscordConfigForm(forms.ModelForm):
    """The Discord settings: checks the shape of what is typed"""

    class Meta:
        model = DiscordConfig
        fields = "__all__"

    @staticmethod
    def _check_url(url: str) -> str:
        url = url.strip()
        if url and not url.startswith("https://"):
            raise forms.ValidationError("The webhook URL must start with https://")

        return url

    @staticmethod
    def _check_thread(thread_id: str) -> str:
        thread_id = thread_id.strip()
        if thread_id and not thread_id.isdigit():
            raise forms.ValidationError("A thread ID is a number")

        return thread_id

    def clean_new_order_webhook_url(self):
        return self._check_url(self.cleaned_data["new_order_webhook_url"])

    def clean_complete_webhook_url(self):
        return self._check_url(self.cleaned_data["complete_webhook_url"])

    def clean_new_order_thread_id(self):
        return self._check_thread(self.cleaned_data["new_order_thread_id"])

    def clean_complete_thread_id(self):
        return self._check_thread(self.cleaned_data["complete_thread_id"])


@admin.register(DiscordConfig)
class DiscordConfigAdmin(admin.ModelAdmin):
    """
    The Discord webhooks. A webhook URL is a secret: whoever has it can write to
    the channel, so it is edited here and not on the plugin pages.
    """

    form = DiscordConfigForm
    list_display = (
        "__str__",
        "new_order_configured",
        "complete_configured",
        "updated_at",
    )
    readonly_fields = ("updated_at",)
    fieldsets = (
        (
            "Channel for new orders",
            {
                "description": "New, changed and deleted orders.",
                "fields": ("new_order_webhook_url", "new_order_thread_id"),
            },
        ),
        (
            "Channel for reports",
            {
                "description": (
                    "Contracts waiting for acceptance, credited and invalid "
                    "contracts, items taken and given back, ESI token problems."
                ),
                "fields": ("complete_webhook_url", "complete_thread_id"),
            },
        ),
        ("Options", {"fields": ("notify_taken", "updated_at")}),
    )

    def has_add_permission(self, request):
        """Only one row is allowed"""

        return not DiscordConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        """The row stays; to switch a channel off, empty its fields"""

        return False

    @admin.display(boolean=True, description="Channel for new orders")
    def new_order_configured(self, obj):
        return bool(obj.new_order_webhook_url)

    @admin.display(boolean=True, description="Channel for reports")
    def complete_configured(self, obj):
        return bool(obj.complete_webhook_url)
