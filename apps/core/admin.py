from django.contrib import admin

from .models import Sequence


@admin.register(Sequence)
class SequenceAdmin(admin.ModelAdmin):
    list_display = ("school", "key", "value")
    list_filter = ("school",)
    readonly_fields = ("school", "key", "value")
