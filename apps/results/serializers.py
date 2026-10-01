from rest_framework import serializers

from apps.core.fields import SchoolPK
from apps.schools.models import Term

from .models import ClassResult, ResultSummary, ScoreSheet


class ScoreSheetListSerializer(serializers.ModelSerializer):
    classroom_name = serializers.CharField(source="classroom.name", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    teacher_name = serializers.CharField(source="teacher.full_name", read_only=True, default=None)
    term_name = serializers.CharField(source="term.__str__", read_only=True)
    class_result_status = serializers.CharField(source="class_result.status", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    progress = serializers.SerializerMethodField()

    class Meta:
        model = ScoreSheet
        fields = [
            "id",
            "term",
            "term_name",
            "class_result",
            "class_result_status",
            "classroom",
            "classroom_name",
            "subject",
            "subject_name",
            "teacher",
            "teacher_name",
            "status",
            "status_label",
            "progress",
            "submitted_at",
            "returned_at",
            "return_note",
            "updated_at",
        ]
        read_only_fields = fields

    def get_progress(self, obj) -> dict:
        from .services import sheet_progress

        return sheet_progress(obj)


class ScoreRowSerializer(serializers.Serializer):
    student = serializers.IntegerField()
    full_name = serializers.CharField()
    admission_number = serializers.CharField()
    ca1 = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    ca2 = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    exam = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    total = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    grade = serializers.CharField(allow_blank=True)
    remark = serializers.CharField(allow_blank=True)


class ScoreSheetDetailSerializer(ScoreSheetListSerializer):
    rows = serializers.SerializerMethodField()
    maxima = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta(ScoreSheetListSerializer.Meta):
        fields = ScoreSheetListSerializer.Meta.fields + ["maxima", "can_edit", "rows"]
        read_only_fields = fields

    def get_rows(self, obj) -> list[dict]:
        from .services import sheet_rows

        return ScoreRowSerializer(sheet_rows(obj), many=True).data

    def get_maxima(self, obj) -> dict:
        settings_obj = obj.school.settings
        return {"ca1": settings_obj.ca1_max, "ca2": settings_obj.ca2_max, "exam": settings_obj.exam_max}

    def get_can_edit(self, obj) -> bool:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return bool(
            user
            and user.role == "teacher"
            and obj.teacher_id == user.id
            and obj.status != "submitted"
            and obj.class_result.status == "open"
        )


class ScoreEntrySerializer(serializers.Serializer):
    student = serializers.IntegerField()
    ca1 = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True, required=False, min_value=0)
    ca2 = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True, required=False, min_value=0)
    exam = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True, required=False, min_value=0)


class ScoreBulkSerializer(serializers.Serializer):
    scores = ScoreEntrySerializer(many=True, allow_empty=False)


class ReturnSheetSerializer(serializers.Serializer):
    note = serializers.CharField(help_text="Tell the teacher what to fix.")


class UnlockSerializer(serializers.Serializer):
    reason = serializers.CharField(help_text="Why published results are being reopened. Written to the audit log.")


class ClassResultSerializer(serializers.ModelSerializer):
    classroom_name = serializers.CharField(source="classroom.name", read_only=True)
    term_name = serializers.CharField(source="term.__str__", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    sheets_total = serializers.IntegerField(read_only=True, default=0)
    sheets_submitted = serializers.IntegerField(read_only=True, default=0)
    approved_by_name = serializers.CharField(source="approved_by.full_name", read_only=True, default=None)
    published_by_name = serializers.CharField(source="published_by.full_name", read_only=True, default=None)

    class Meta:
        model = ClassResult
        fields = [
            "id",
            "term",
            "term_name",
            "classroom",
            "classroom_name",
            "status",
            "status_label",
            "sheets_total",
            "sheets_submitted",
            "class_average",
            "next_term_begins",
            "review_started_at",
            "approved_by",
            "approved_by_name",
            "approved_at",
            "published_by",
            "published_by_name",
            "published_at",
        ]
        read_only_fields = [f for f in fields if f != "next_term_begins"]


class ResultSummarySerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    admission_number = serializers.CharField(source="student.admission_number", read_only=True)
    classroom_name = serializers.CharField(source="class_result.classroom.name", read_only=True)
    status = serializers.CharField(source="class_result.status", read_only=True)

    class Meta:
        model = ResultSummary
        fields = [
            "id",
            "class_result",
            "status",
            "student",
            "student_name",
            "admission_number",
            "classroom_name",
            "total",
            "average",
            "subjects_count",
            "position",
            "class_size",
            "class_teacher_comment",
            "principal_comment",
            "updated_at",
        ]
        read_only_fields = [f for f in fields if f not in ("class_teacher_comment", "principal_comment")]


class SetupSerializer(serializers.Serializer):
    term = SchoolPK(queryset=Term.objects.all(), required=False, help_text="Defaults to the current term")
