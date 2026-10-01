from django.contrib import admin

from .models import NotificationLog


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "school", "channel", "recipient", "purpose", "status")
    list_filter = ("school", "channel", "status", "purpose")
    search_fields = ("recipient", "subject", "body")
    readonly_fields = [f.name for f in NotificationLog._meta.fields]
