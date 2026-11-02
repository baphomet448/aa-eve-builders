"""Admin models"""

# Django
from django.contrib import admin

# AA EVE Builders
from evebuilders.models import (
    BuilderProfile,
    CatalogSync,
    ContractRecord,
    ContractSource,
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
