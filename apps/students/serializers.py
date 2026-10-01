import json

from rest_framework import serializers

from apps.core.fields import SchoolPK
from apps.schools.models import ClassRoom

from .models import Guardian, Student, StudentImport


class GuardianBriefSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Guardian
        fields = ["id", "full_name", "relationship", "phone", "email"]
        read_only_fields = fields


class GuardianSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    students = serializers.SerializerMethodField()

    class Meta:
        model = Guardian
        fields = [
            "id",
            "first_name",
            "last_name",
            "full_name",
            "relationship",
            "phone",
            "alt_phone",
            "email",
            "address",
            "occupation",
            "students",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_students(self, obj) -> list[dict]:
        visible = self.context.get("visible_student_ids")
        result = []
        for s in obj.students.all():
            if visible is not None and s.id not in visible:
                continue
            result.append(
                {
                    "id": s.id,
                    "full_name": s.full_name,
                    "admission_number": s.admission_number,
                    "classroom": s.classroom.name if s.classroom_id else None,
                }
            )
        return result


class ClassRoomRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class StudentListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    classroom = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            "id",
            "admission_number",
            "first_name",
            "middle_name",
            "last_name",
            "full_name",
            "gender",
            "classroom",
            "status",
            "photo",
        ]
        read_only_fields = fields

    def get_classroom(self, obj) -> dict | None:
        if not obj.classroom_id:
            return None
        return {"id": obj.classroom_id, "name": obj.classroom.name}


class StudentBasicSerializer(serializers.ModelSerializer):
    """What a bursar sees: enough to identify the student and contact the family."""

    full_name = serializers.CharField(read_only=True)
    classroom = serializers.SerializerMethodField()
    guardians = GuardianBriefSerializer(many=True, read_only=True)

    class Meta:
        model = Student
        fields = ["id", "admission_number", "full_name", "classroom", "status", "guardians"]
        read_only_fields = fields

    def get_classroom(self, obj) -> dict | None:
        if not obj.classroom_id:
            return None
        return {"id": obj.classroom_id, "name": obj.classroom.name}


class StudentSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    classroom = SchoolPK(queryset=ClassRoom.objects.all(), allow_null=True, required=False)
    classroom_name = serializers.CharField(source="classroom.name", read_only=True, default=None)
    guardians = GuardianBriefSerializer(many=True, read_only=True)
    guardian_ids = SchoolPK(
        queryset=Guardian.objects.all(), many=True, write_only=True, required=False, source="guardians"
    )

    class Meta:
        model = Student
        fields = [
            "id",
            "admission_number",
            "first_name",
            "middle_name",
            "last_name",
            "full_name",
            "gender",
            "date_of_birth",
            "classroom",
            "classroom_name",
            "status",
            "admission_date",
            "address",
            "photo",
            "guardians",
            "guardian_ids",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_admission_number(self, value):
        value = value.strip()
        qs = Student.objects.filter(school=self.context["school"], admission_number__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Another student already has this admission number.")
        return value


class StudentImportPreviewRequestSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="A .csv or .xlsx file with one student per row.")
    column_mapping = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text='Optional JSON object {"Header in file": "field"} to override automatic detection.',
    )

    def validate_file(self, value):
        name = value.name.lower()
        if not name.endswith((".csv", ".xlsx", ".xlsm")):
            raise serializers.ValidationError("Upload a .csv or .xlsx file.")
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("The file is larger than 5 MB.")
        return value

    def validate_column_mapping(self, value):
        if not value:
            return {}
        try:
            data = json.loads(value)
        except json.JSONDecodeError as exc:
            raise serializers.ValidationError("column_mapping must be a JSON object.") from exc
        if not isinstance(data, dict):
            raise serializers.ValidationError("column_mapping must be a JSON object.")
        return data


class StudentImportSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source="uploaded_by.full_name", read_only=True, default=None)
    error_count = serializers.SerializerMethodField()

    class Meta:
        model = StudentImport
        fields = [
            "id",
            "original_filename",
            "status",
            "column_mapping",
            "total_rows",
            "valid_rows",
            "error_count",
            "error_rows",
            "created_count",
            "uploaded_by",
            "uploaded_by_name",
            "created_at",
            "completed_at",
        ]
        read_only_fields = fields

    def get_error_count(self, obj) -> int:
        return len(obj.error_rows or [])
