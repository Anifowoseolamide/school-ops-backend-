from django.contrib import admin

from .models import Guardian, Student, StudentImport


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("admission_number", "last_name", "first_name", "classroom", "status", "school")
    list_filter = ("school", "status", "gender", "classroom__level")
    search_fields = ("admission_number", "first_name", "last_name")
    filter_horizontal = ("guardians",)


@admin.register(Guardian)
class GuardianAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "relationship", "phone", "email", "school")
    list_filter = ("school",)
    search_fields = ("first_name", "last_name", "phone", "email")


@admin.register(StudentImport)
class StudentImportAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "school", "status", "total_rows", "created_count", "created_at")
    list_filter = ("school", "status")
    readonly_fields = ("error_rows", "column_mapping")
