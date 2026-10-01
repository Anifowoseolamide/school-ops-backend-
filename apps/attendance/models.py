from django.conf import settings
from django.db import models

from apps.core.models import SchoolOwnedModel


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", "Present"
    ABSENT = "absent", "Absent"
    LATE = "late", "Late"
    EXCUSED = "excused", "Excused absence"


# Statuses that count as "in school" for attendance percentages.
ATTENDED = (AttendanceStatus.PRESENT, AttendanceStatus.LATE)


class AttendanceRecord(SchoolOwnedModel):
    """One student's attendance for one school day."""

    student = models.ForeignKey("students.Student", on_delete=models.PROTECT, related_name="attendance_records")
    classroom = models.ForeignKey("schools.ClassRoom", on_delete=models.PROTECT, related_name="attendance_records")
    term = models.ForeignKey("schools.Term", on_delete=models.PROTECT, related_name="attendance_records")
    date = models.DateField(db_index=True)
    status = models.CharField(max_length=10, choices=AttendanceStatus.choices, default=AttendanceStatus.PRESENT)
    note = models.CharField(max_length=255, blank=True)
    marked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-date", "student__last_name"]
        constraints = [models.UniqueConstraint(fields=["student", "date"], name="uniq_attendance_per_student_day")]
        indexes = [models.Index(fields=["classroom", "date"]), models.Index(fields=["school", "date"])]

    def __str__(self):
        return f"{self.student} {self.date} {self.status}"
