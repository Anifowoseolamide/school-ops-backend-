from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import SchoolOwnedModel, TimeStampedModel


class ClassLevel(models.TextChoices):
    JSS1 = "JSS1", "JSS 1"
    JSS2 = "JSS2", "JSS 2"
    JSS3 = "JSS3", "JSS 3"
    SS1 = "SS1", "SS 1"
    SS2 = "SS2", "SS 2"
    SS3 = "SS3", "SS 3"


LEVEL_ORDER = {level: index for index, level in enumerate(ClassLevel.values, start=1)}


class TermName(models.TextChoices):
    FIRST = "first", "First Term"
    SECOND = "second", "Second Term"
    THIRD = "third", "Third Term"


class School(TimeStampedModel):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    motto = models.CharField(max_length=200, blank=True)
    logo = models.ImageField(upload_to="school-logos/", blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SchoolSettings(TimeStampedModel):
    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name="settings")

    # Results
    ca1_max = models.PositiveSmallIntegerField(default=20)
    ca2_max = models.PositiveSmallIntegerField(default=20)
    exam_max = models.PositiveSmallIntegerField(default=60)

    # Fees
    allow_part_payment = models.BooleanField(default=True)
    minimum_part_payment_kobo = models.PositiveBigIntegerField(
        default=0, help_text="Smallest online part payment a parent may make, in kobo. 0 = no minimum."
    )
    invoice_prefix = models.CharField(max_length=10, default="INV")
    receipt_prefix = models.CharField(max_length=10, default="RCT")

    # Report cards
    hold_report_cards_for_debtors = models.BooleanField(
        default=False,
        help_text="If on, parents cannot open the report card link while the term invoice has a balance.",
    )
    report_card_footer = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name_plural = "school settings"

    def __str__(self):
        return f"Settings for {self.school}"

    @property
    def max_total(self) -> int:
        return self.ca1_max + self.ca2_max + self.exam_max

    def clean(self):
        if self.max_total != 100:
            raise ValidationError("CA1, CA2 and exam maximums must add up to 100.")


class AcademicSession(SchoolOwnedModel):
    name = models.CharField(max_length=20, help_text="e.g. 2026/2027")
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ["-start_date"]
        constraints = [models.UniqueConstraint(fields=["school", "name"], name="uniq_session_name_per_school")]

    def __str__(self):
        return self.name

    def clean(self):
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValidationError({"end_date": "End date must be after the start date."})


class Term(SchoolOwnedModel):
    session = models.ForeignKey(AcademicSession, on_delete=models.CASCADE, related_name="terms")
    name = models.CharField(max_length=10, choices=TermName.choices)
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ["-start_date"]
        constraints = [models.UniqueConstraint(fields=["session", "name"], name="uniq_term_per_session")]

    def __str__(self):
        return f"{self.get_name_display()} {self.session.name}"

    def clean(self):
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValidationError({"end_date": "End date must be after the start date."})

    def contains(self, day) -> bool:
        return self.start_date <= day <= self.end_date


class ClassRoom(SchoolOwnedModel):
    """A class arm, e.g. JSS 2A."""

    level = models.CharField(max_length=5, choices=ClassLevel.choices)
    arm = models.CharField(max_length=10, help_text="e.g. A, B, Gold")
    level_order = models.PositiveSmallIntegerField(default=0, editable=False)
    class_teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="form_classes",
    )
    capacity = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["level_order", "arm"]
        constraints = [models.UniqueConstraint(fields=["school", "level", "arm"], name="uniq_class_arm_per_school")]

    def __str__(self):
        return self.name

    @property
    def name(self) -> str:
        return f"{self.get_level_display()}{self.arm}"

    def save(self, *args, **kwargs):
        self.arm = (self.arm or "").strip().upper()
        self.level_order = LEVEL_ORDER.get(self.level, 0)
        super().save(*args, **kwargs)


class Subject(SchoolOwnedModel):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["school", "name"], name="uniq_subject_name_per_school")]

    def __str__(self):
        return self.name


class TeacherAssignment(SchoolOwnedModel):
    """Who teaches which subject to which class in an academic session.

    This is what "my students" and "my subjects" mean for a teacher.
    """

    session = models.ForeignKey(AcademicSession, on_delete=models.CASCADE, related_name="assignments")
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, related_name="assignments")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="assignments")
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="teaching_assignments"
    )

    class Meta:
        ordering = ["classroom__level_order", "classroom__arm", "subject__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "classroom", "subject"], name="uniq_subject_teacher_per_class_session"
            )
        ]

    def __str__(self):
        return f"{self.teacher} - {self.subject} - {self.classroom}"


class GradeBand(SchoolOwnedModel):
    """A row of the grading scale, e.g. A1 = 75 to 100, Excellent."""

    grade = models.CharField(max_length=5)
    min_score = models.DecimalField(
        max_digits=5, decimal_places=2, validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))]
    )
    max_score = models.DecimalField(
        max_digits=5, decimal_places=2, validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))]
    )
    remark = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ["-min_score"]
        constraints = [
            models.UniqueConstraint(fields=["school", "grade"], name="uniq_grade_per_school"),
            models.UniqueConstraint(fields=["school", "min_score"], name="uniq_grade_min_per_school"),
        ]

    def __str__(self):
        return f"{self.grade} ({self.min_score}-{self.max_score})"

    def clean(self):
        if self.min_score is not None and self.max_score is not None and self.min_score > self.max_score:
            raise ValidationError("Minimum score cannot be greater than maximum score.")
