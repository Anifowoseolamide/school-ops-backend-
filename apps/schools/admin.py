from django.contrib import admin

from .models import AcademicSession, ClassRoom, GradeBand, School, SchoolSettings, Subject, TeacherAssignment, Term


class SchoolSettingsInline(admin.StackedInline):
    model = SchoolSettings
    can_delete = False


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "phone", "email", "is_active", "created_at")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [SchoolSettingsInline]


@admin.register(AcademicSession)
class AcademicSessionAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "start_date", "end_date", "is_current")
    list_filter = ("school", "is_current")


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ("__str__", "school", "start_date", "end_date", "is_current")
    list_filter = ("school", "is_current", "name")


@admin.register(ClassRoom)
class ClassRoomAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "class_teacher", "capacity")
    list_filter = ("school", "level")


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "school")
    list_filter = ("school",)
    search_fields = ("name", "code")


@admin.register(TeacherAssignment)
class TeacherAssignmentAdmin(admin.ModelAdmin):
    list_display = ("teacher", "subject", "classroom", "session", "school")
    list_filter = ("school", "session")


@admin.register(GradeBand)
class GradeBandAdmin(admin.ModelAdmin):
    list_display = ("grade", "min_score", "max_score", "remark", "school")
    list_filter = ("school",)
