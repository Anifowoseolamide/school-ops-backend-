"""Results.

Structure
---------
* ClassResult: one per class per term. Holds the class-level workflow status.
* ScoreSheet:  one per subject per class per term, owned by the subject teacher.
* Score:       one student's CA1, CA2 and exam for a sheet.
* ResultSummary: one student's total, average, position and comments for the term.

Workflow
--------
Sheet:  draft -> submitted (teacher) -> returned (admin, with a note) -> submitted ...
Class:  open -> in_review (admin, once every sheet is submitted)
             -> approved (principal) -> published (principal)
        published -> in_review (principal "unlock", reason required, audited)
"""
from django.conf import settings
from django.db import models

from apps.core.models import SchoolOwnedModel, TimeStampedModel


class SheetStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    RETURNED = "returned", "Returned to teacher"


class ClassResultStatus(models.TextChoices):
    OPEN = "open", "Open for score entry"
    IN_REVIEW = "in_review", "In review"
    APPROVED = "approved", "Approved"
    PUBLISHED = "published", "Published"


class ClassResult(SchoolOwnedModel):
    term = models.ForeignKey("schools.Term", on_delete=models.PROTECT, related_name="class_results")
    classroom = models.ForeignKey("schools.ClassRoom", on_delete=models.PROTECT, related_name="class_results")
    status = models.CharField(max_length=12, choices=ClassResultStatus.choices, default=ClassResultStatus.OPEN, db_index=True)
    class_average = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    review_started_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    review_started_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    published_at = models.DateTimeField(null=True, blank=True)
    next_term_begins = models.DateField(null=True, blank=True, help_text="Printed on report cards")

    class Meta:
        ordering = ["classroom__level_order", "classroom__arm"]
        constraints = [models.UniqueConstraint(fields=["term", "classroom"], name="uniq_class_result_per_term")]

    def __str__(self):
        return f"{self.classroom} - {self.term}"


class ScoreSheet(SchoolOwnedModel):
    class_result = models.ForeignKey(ClassResult, on_delete=models.CASCADE, related_name="sheets")
    term = models.ForeignKey("schools.Term", on_delete=models.PROTECT, related_name="score_sheets")
    classroom = models.ForeignKey("schools.ClassRoom", on_delete=models.PROTECT, related_name="score_sheets")
    subject = models.ForeignKey("schools.Subject", on_delete=models.PROTECT, related_name="score_sheets")
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="score_sheets")
    status = models.CharField(max_length=10, choices=SheetStatus.choices, default=SheetStatus.DRAFT, db_index=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    returned_at = models.DateTimeField(null=True, blank=True)
    returned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    return_note = models.TextField(blank=True)

    class Meta:
        ordering = ["classroom__level_order", "classroom__arm", "subject__name"]
        constraints = [models.UniqueConstraint(fields=["term", "classroom", "subject"], name="uniq_sheet_per_subject_class_term")]

    def __str__(self):
        return f"{self.subject} - {self.classroom} - {self.term}"


class Score(TimeStampedModel):
    sheet = models.ForeignKey(ScoreSheet, on_delete=models.CASCADE, related_name="scores")
    student = models.ForeignKey("students.Student", on_delete=models.PROTECT, related_name="scores")
    ca1 = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    ca2 = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    exam = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    total = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    grade = models.CharField(max_length=5, blank=True)
    remark = models.CharField(max_length=50, blank=True)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["student__last_name", "student__first_name"]
        constraints = [models.UniqueConstraint(fields=["sheet", "student"], name="uniq_score_per_sheet_student")]

    def __str__(self):
        return f"{self.student} {self.sheet.subject}: {self.total}"

    @property
    def is_complete(self) -> bool:
        return self.ca1 is not None and self.ca2 is not None and self.exam is not None


class ResultSummary(SchoolOwnedModel):
    class_result = models.ForeignKey(ClassResult, on_delete=models.CASCADE, related_name="summaries")
    student = models.ForeignKey("students.Student", on_delete=models.PROTECT, related_name="result_summaries")
    total = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    average = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    subjects_count = models.PositiveSmallIntegerField(default=0)
    position = models.PositiveSmallIntegerField(null=True, blank=True)
    class_size = models.PositiveSmallIntegerField(default=0)
    class_teacher_comment = models.TextField(blank=True)
    principal_comment = models.TextField(blank=True)

    class Meta:
        ordering = ["position", "student__last_name"]
        constraints = [models.UniqueConstraint(fields=["class_result", "student"], name="uniq_summary_per_student")]
        verbose_name_plural = "result summaries"

    def __str__(self):
        return f"{self.student} - {self.class_result}"
