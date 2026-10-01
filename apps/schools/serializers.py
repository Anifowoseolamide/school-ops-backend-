from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.core.fields import SchoolPK
from apps.core.roles import TEACHER

from .models import AcademicSession, ClassRoom, GradeBand, School, SchoolSettings, Subject, TeacherAssignment, Term

User = get_user_model()


class SchoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = School
        fields = ["id", "name", "slug", "address", "phone", "email", "website", "motto", "logo", "created_at"]
        read_only_fields = ["id", "slug", "created_at"]


class SchoolSettingsSerializer(serializers.ModelSerializer):
    max_total = serializers.IntegerField(read_only=True)

    class Meta:
        model = SchoolSettings
        fields = [
            "ca1_max",
            "ca2_max",
            "exam_max",
            "max_total",
            "allow_part_payment",
            "minimum_part_payment_kobo",
            "invoice_prefix",
            "receipt_prefix",
            "hold_report_cards_for_debtors",
            "report_card_footer",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]

    def validate(self, attrs):
        ca1 = attrs.get("ca1_max", getattr(self.instance, "ca1_max", 0))
        ca2 = attrs.get("ca2_max", getattr(self.instance, "ca2_max", 0))
        exam = attrs.get("exam_max", getattr(self.instance, "exam_max", 0))
        if ca1 + ca2 + exam != 100:
            raise serializers.ValidationError("CA1, CA2 and exam maximums must add up to 100.")
        return attrs


class AcademicSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicSession
        fields = ["id", "name", "start_date", "end_date", "is_current", "created_at"]
        read_only_fields = ["id", "is_current", "created_at"]

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end <= start:
            raise serializers.ValidationError({"end_date": "End date must be after the start date."})
        name = attrs.get("name")
        school = self.context["school"]
        if name:
            qs = AcademicSession.objects.filter(school=school, name=name)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({"name": "A session with this name already exists."})
        return attrs


class TermSerializer(serializers.ModelSerializer):
    session = SchoolPK(queryset=AcademicSession.objects.all())
    session_name = serializers.CharField(source="session.name", read_only=True)
    label = serializers.SerializerMethodField()

    class Meta:
        model = Term
        fields = ["id", "session", "session_name", "name", "label", "start_date", "end_date", "is_current", "created_at"]
        read_only_fields = ["id", "is_current", "created_at"]

    def get_label(self, obj) -> str:
        return str(obj)

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        session = attrs.get("session", getattr(self.instance, "session", None))
        name = attrs.get("name", getattr(self.instance, "name", None))
        if start and end and end <= start:
            raise serializers.ValidationError({"end_date": "End date must be after the start date."})
        if session and start and end and (start < session.start_date or end > session.end_date):
            raise serializers.ValidationError("Term dates must fall inside the academic session dates.")
        if session and name:
            qs = Term.objects.filter(session=session, name=name)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({"name": "This term already exists in the session."})
        return attrs


class ClassRoomSerializer(serializers.ModelSerializer):
    name = serializers.CharField(read_only=True)
    level_label = serializers.CharField(source="get_level_display", read_only=True)
    class_teacher = SchoolPK(queryset=User.objects.all(), allow_null=True, required=False)
    class_teacher_name = serializers.CharField(source="class_teacher.full_name", read_only=True, default=None)
    student_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = ClassRoom
        fields = [
            "id",
            "name",
            "level",
            "level_label",
            "arm",
            "class_teacher",
            "class_teacher_name",
            "capacity",
            "student_count",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_class_teacher(self, value):
        if value is not None and (value.role != TEACHER or not value.is_active):
            raise serializers.ValidationError("The class teacher must be an active teacher.")
        return value

    def validate(self, attrs):
        level = attrs.get("level", getattr(self.instance, "level", None))
        arm = (attrs.get("arm", getattr(self.instance, "arm", "")) or "").strip().upper()
        qs = ClassRoom.objects.filter(school=self.context["school"], level=level, arm=arm)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("This class already exists.")
        return attrs


class ClassRoomBriefSerializer(serializers.ModelSerializer):
    name = serializers.CharField(read_only=True)

    class Meta:
        model = ClassRoom
        fields = ["id", "name", "level", "arm"]
        read_only_fields = fields


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ["id", "name", "code", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_name(self, value):
        value = value.strip()
        qs = Subject.objects.filter(school=self.context["school"], name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A subject with this name already exists.")
        return value


class TeacherAssignmentSerializer(serializers.ModelSerializer):
    session = SchoolPK(queryset=AcademicSession.objects.all())
    classroom = SchoolPK(queryset=ClassRoom.objects.all())
    subject = SchoolPK(queryset=Subject.objects.all())
    teacher = SchoolPK(queryset=User.objects.all())
    classroom_name = serializers.CharField(source="classroom.name", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    teacher_name = serializers.CharField(source="teacher.full_name", read_only=True)
    session_name = serializers.CharField(source="session.name", read_only=True)

    class Meta:
        model = TeacherAssignment
        fields = [
            "id",
            "session",
            "session_name",
            "classroom",
            "classroom_name",
            "subject",
            "subject_name",
            "teacher",
            "teacher_name",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_teacher(self, value):
        if value.role != TEACHER or not value.is_active:
            raise serializers.ValidationError("Assignments can only be given to active teachers.")
        return value

    def validate(self, attrs):
        session = attrs.get("session", getattr(self.instance, "session", None))
        classroom = attrs.get("classroom", getattr(self.instance, "classroom", None))
        subject = attrs.get("subject", getattr(self.instance, "subject", None))
        qs = TeacherAssignment.objects.filter(session=session, classroom=classroom, subject=subject)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "This subject already has a teacher in this class for the session. Edit that assignment instead."
            )
        return attrs


class GradeBandSerializer(serializers.ModelSerializer):
    class Meta:
        model = GradeBand
        fields = ["id", "grade", "min_score", "max_score", "remark"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        lo = attrs.get("min_score", getattr(self.instance, "min_score", None))
        hi = attrs.get("max_score", getattr(self.instance, "max_score", None))
        if lo is not None and hi is not None and lo > hi:
            raise serializers.ValidationError("Minimum score cannot be greater than maximum score.")
        school = self.context["school"]
        for field, value in (("grade", attrs.get("grade")), ("min_score", attrs.get("min_score"))):
            if value is None:
                continue
            qs = GradeBand.objects.filter(school=school, **{field: value})
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({field: "Another grade band already uses this value."})
        return attrs
