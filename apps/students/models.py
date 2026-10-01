from django.conf import settings
from django.db import models

from apps.core.models import SchoolOwnedModel


class Gender(models.TextChoices):
    MALE = "male", "Male"
    FEMALE = "female", "Female"


class StudentStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    WITHDRAWN = "withdrawn", "Withdrawn"
    GRADUATED = "graduated", "Graduated"


class Guardian(SchoolOwnedModel):
    """A parent or guardian. One guardian can be linked to several students (siblings)."""

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    relationship = models.CharField(max_length=30, blank=True, help_text="e.g. Father, Mother, Aunt")
    phone = models.CharField(max_length=30, db_index=True)
    alt_phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    occupation = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class Student(SchoolOwnedModel):
    admission_number = models.CharField(max_length=50)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    gender = models.CharField(max_length=10, choices=Gender.choices, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    classroom = models.ForeignKey(
        "schools.ClassRoom", on_delete=models.SET_NULL, null=True, blank=True, related_name="students"
    )
    status = models.CharField(
        max_length=15, choices=StudentStatus.choices, default=StudentStatus.ACTIVE, db_index=True
    )
    admission_date = models.DateField(null=True, blank=True)
    address = models.TextField(blank=True)
    photo = models.ImageField(upload_to="student-photos/", blank=True)
    guardians = models.ManyToManyField(Guardian, blank=True, related_name="students")

    class Meta:
        ordering = ["last_name", "first_name"]
        constraints = [
            models.UniqueConstraint(fields=["school", "admission_number"], name="uniq_admission_number_per_school")
        ]
        indexes = [models.Index(fields=["school", "classroom", "status"])]

    def __str__(self):
        return f"{self.full_name} ({self.admission_number})"

    @property
    def full_name(self) -> str:
        return " ".join(p for p in [self.first_name, self.middle_name, self.last_name] if p)

    @property
    def primary_guardian(self):
        return self.guardians.order_by("id").first()


class ImportStatus(models.TextChoices):
    PREVIEWED = "previewed", "Previewed"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class StudentImport(SchoolOwnedModel):
    """An uploaded Excel/CSV file of students: preview first, then commit."""

    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    file = models.FileField(upload_to="imports/")
    original_filename = models.CharField(max_length=255)
    status = models.CharField(max_length=15, choices=ImportStatus.choices, default=ImportStatus.PREVIEWED)
    column_mapping = models.JSONField(default=dict, blank=True, help_text="{field: header in file}")
    total_rows = models.PositiveIntegerField(default=0)
    valid_rows = models.PositiveIntegerField(default=0)
    error_rows = models.JSONField(default=list, blank=True)
    created_count = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.original_filename} ({self.status})"
