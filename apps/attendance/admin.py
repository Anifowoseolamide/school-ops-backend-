from django.contrib import admin

from .models import AttendanceRecord


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("date", "student", "classroom", "status", "marked_by", "school")
    list_filter = ("school", "status", "classroom")
    date_hierarchy = "date"
    search_fields = ("student__first_name", "student__last_name", "student__admission_number")
