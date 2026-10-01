from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "school", "actor_email", "actor_role", "action", "object_repr")
    list_filter = ("school", "actor_role", "action")
    search_fields = ("actor_email", "action", "object_repr")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
