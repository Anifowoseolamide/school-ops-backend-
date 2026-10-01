from django.contrib import admin

from .models import ClassResult, ResultSummary, Score, ScoreSheet


@admin.register(ClassResult)
class ClassResultAdmin(admin.ModelAdmin):
    list_display = ("classroom", "term", "status", "class_average", "published_at", "school")
    list_filter = ("school", "term", "status")


@admin.register(ScoreSheet)
class ScoreSheetAdmin(admin.ModelAdmin):
    list_display = ("subject", "classroom", "term", "teacher", "status", "submitted_at")
    list_filter = ("school", "term", "status", "subject")


@admin.register(Score)
class ScoreAdmin(admin.ModelAdmin):
    list_display = ("student", "sheet", "ca1", "ca2", "exam", "total", "grade")
    list_filter = ("sheet__term", "sheet__subject")
    search_fields = ("student__last_name", "student__admission_number")


@admin.register(ResultSummary)
class ResultSummaryAdmin(admin.ModelAdmin):
    list_display = ("student", "class_result", "total", "average", "position", "class_size")
    list_filter = ("class_result__term",)
