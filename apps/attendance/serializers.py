from django.utils import timezone
from rest_framework import serializers

from apps.core.fields import SchoolPK
from apps.schools.models import ClassRoom

from .models import AttendanceRecord, AttendanceStatus


class AttendanceRecordSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    admission_number = serializers.CharField(source="student.admission_number", read_only=True)
    classroom_name = serializers.CharField(source="classroom.name", read_only=True)
    marked_by_name = serializers.CharField(source="marked_by.full_name", read_only=True, default=None)

    class Meta:
        model = AttendanceRecord
        fields = [
            "id",
            "date",
            "student",
            "student_name",
            "admission_number",
            "classroom",
            "classroom_name",
            "term",
            "status",
            "note",
            "marked_by",
            "marked_by_name",
            "updated_at",
        ]
        read_only_fields = fields


class RegisterQuerySerializer(serializers.Serializer):
    classroom = SchoolPK(queryset=ClassRoom.objects.all())
    date = serializers.DateField(required=False)

    def validate_date(self, value):
        if value and value > timezone.localdate():
            raise serializers.ValidationError("Attendance cannot be recorded for a future date.")
        return value


class RegisterEntrySerializer(serializers.Serializer):
    student = serializers.IntegerField()
    status = serializers.ChoiceField(choices=AttendanceStatus.choices)
    note = serializers.CharField(required=False, allow_blank=True, max_length=255)


class RegisterSaveSerializer(RegisterQuerySerializer):
    records = RegisterEntrySerializer(
        many=True,
        required=False,
        help_text="Only absent/late/excused students need to be sent; everyone else is marked present.",
    )


class RegisterStudentSerializer(serializers.Serializer):
    student = serializers.IntegerField()
    full_name = serializers.CharField()
    admission_number = serializers.CharField()
    status = serializers.CharField()
    note = serializers.CharField(allow_blank=True)
    is_marked = serializers.BooleanField()


class RegisterResponseSerializer(serializers.Serializer):
    classroom = serializers.DictField()
    date = serializers.DateField()
    term = serializers.DictField(allow_null=True)
    is_marked = serializers.BooleanField()
    marked_by = serializers.CharField(allow_null=True)
    marked_at = serializers.DateTimeField(allow_null=True)
    students = RegisterStudentSerializer(many=True)
