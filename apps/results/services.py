"""Results business logic: setup, score entry, workflow transitions and ranking."""
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.exceptions import WorkflowError
from apps.schools.models import ClassRoom, GradeBand, TeacherAssignment
from apps.schools.services import get_settings, grade_for
from apps.students.models import Student, StudentStatus

from .models import ClassResult, ClassResultStatus, ResultSummary, Score, ScoreSheet, SheetStatus

TWO_PLACES = Decimal("0.01")


def _q(value) -> Decimal:
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
@transaction.atomic
def setup_term(term) -> dict:
    """Create the class results and score sheets for a term from the teacher assignments.

    Idempotent: run it again after adding classes or assignments. Sheets that have
    not been submitted pick up teacher changes.
    """
    created_results = created_sheets = updated_sheets = 0
    assignments = TeacherAssignment.objects.filter(school=term.school, session=term.session).select_related("classroom", "subject")
    by_class: dict[int, list] = {}
    for a in assignments:
        by_class.setdefault(a.classroom_id, []).append(a)
    for classroom in ClassRoom.objects.filter(school=term.school):
        class_result, created = ClassResult.objects.get_or_create(
            school=term.school, term=term, classroom=classroom
        )
        created_results += int(created)
        for a in by_class.get(classroom.id, []):
            sheet, created = ScoreSheet.objects.get_or_create(
                school=term.school,
                term=term,
                classroom=classroom,
                subject=a.subject,
                defaults={"class_result": class_result, "teacher": a.teacher},
            )
            if created:
                created_sheets += 1
            elif sheet.teacher_id != a.teacher_id and sheet.status != SheetStatus.SUBMITTED:
                sheet.teacher = a.teacher
                sheet.save(update_fields=["teacher", "updated_at"])
                updated_sheets += 1
    return {"class_results_created": created_results, "sheets_created": created_sheets, "sheets_reassigned": updated_sheets}


def get_bands(school):
    return list(GradeBand.objects.filter(school=school).order_by("-min_score"))


# ---------------------------------------------------------------------------
# Score entry
# ---------------------------------------------------------------------------
def sheet_students(sheet):
    """Active students of the class, plus anyone who already has a score on the sheet."""
    scored_ids = sheet.scores.values_list("student_id", flat=True)
    return (
        Student.objects.filter(school=sheet.school)
        .filter(Q(classroom=sheet.classroom, status=StudentStatus.ACTIVE) | Q(id__in=scored_ids))
        .order_by("last_name", "first_name")
        .distinct()
    )


def sheet_rows(sheet) -> list[dict]:
    scores = {s.student_id: s for s in sheet.scores.all()}
    rows = []
    for student in sheet_students(sheet):
        score = scores.get(student.id)
        rows.append(
            {
                "student": student.id,
                "full_name": student.full_name,
                "admission_number": student.admission_number,
                "ca1": score.ca1 if score else None,
                "ca2": score.ca2 if score else None,
                "exam": score.exam if score else None,
                "total": score.total if score else None,
                "grade": score.grade if score else "",
                "remark": score.remark if score else "",
            }
        )
    return rows


def sheet_progress(sheet) -> dict:
    students = sheet_students(sheet).count()
    complete = sheet.scores.filter(ca1__isnull=False, ca2__isnull=False, exam__isnull=False).count()
    return {"students": students, "complete": complete, "missing": max(students - complete, 0)}


def ensure_sheet_editable(sheet):
    if sheet.status == SheetStatus.SUBMITTED:
        raise WorkflowError("This sheet has been submitted. Ask the admin to return it if you need to make changes.")
    if sheet.class_result.status != ClassResultStatus.OPEN:
        raise WorkflowError(
            f"Results for {sheet.classroom} are {sheet.class_result.get_status_display().lower()} and cannot be edited."
        )


@transaction.atomic
def save_scores(sheet, entries: list[dict], user) -> ScoreSheet:
    """Upsert scores. Each entry: {student, ca1?, ca2?, exam?}. Missing keys keep their value."""
    sheet = ScoreSheet.objects.select_for_update().select_related("class_result", "classroom").get(pk=sheet.pk)
    ensure_sheet_editable(sheet)
    school_settings = get_settings(sheet.school)
    maxima = {"ca1": school_settings.ca1_max, "ca2": school_settings.ca2_max, "exam": school_settings.exam_max}
    allowed = set(sheet_students(sheet).values_list("id", flat=True))
    bands = get_bands(sheet.school)
    existing = {s.student_id: s for s in sheet.scores.select_for_update()}
    errors = {}
    for index, entry in enumerate(entries):
        student_id = entry.get("student")
        if student_id not in allowed:
            errors[str(index)] = [f"Student {student_id} is not in {sheet.classroom}."]
            continue
        for field, maximum in maxima.items():
            value = entry.get(field)
            if value is not None and not (Decimal("0") <= Decimal(value) <= maximum):
                errors.setdefault(str(index), []).append(f"{field.upper()} must be between 0 and {maximum}.")
    if errors:
        raise ValidationError({"scores": errors})

    for entry in entries:
        score = existing.get(entry["student"]) or Score(sheet=sheet, student_id=entry["student"])
        for field in ("ca1", "ca2", "exam"):
            if field in entry:
                value = entry[field]
                setattr(score, field, _q(value) if value is not None else None)
        if score.is_complete:
            score.total = _q(score.ca1 + score.ca2 + score.exam)
            score.grade, score.remark = grade_for(score.total, bands)
        else:
            score.total, score.grade, score.remark = None, "", ""
        score.entered_by = user
        score.save()
    # A returned sheet stays "returned" until the teacher submits it again.
    return sheet


@transaction.atomic
def submit_sheet(sheet, user) -> ScoreSheet:
    sheet = ScoreSheet.objects.select_for_update().select_related("class_result", "classroom").get(pk=sheet.pk)
    ensure_sheet_editable(sheet)
    progress = sheet_progress(sheet)
    if progress["students"] == 0:
        raise ValidationError("There are no students in this class.")
    if progress["missing"]:
        raise ValidationError(
            f"{progress['missing']} student(s) are missing a CA1, CA2 or exam score. Every student needs all three."
        )
    sheet.status = SheetStatus.SUBMITTED
    sheet.submitted_at = timezone.now()
    sheet.submitted_by = user
    sheet.save(update_fields=["status", "submitted_at", "submitted_by", "updated_at"])
    return sheet


@transaction.atomic
def return_sheet(sheet, note: str, user) -> ScoreSheet:
    sheet = ScoreSheet.objects.select_for_update().select_related("class_result").get(pk=sheet.pk)
    class_result = ClassResult.objects.select_for_update().get(pk=sheet.class_result_id)
    if sheet.status != SheetStatus.SUBMITTED:
        raise WorkflowError("Only submitted sheets can be returned.")
    if class_result.status not in (ClassResultStatus.OPEN, ClassResultStatus.IN_REVIEW):
        raise WorkflowError("The principal has already approved these results. Ask the principal to send them back first.")
    sheet.status = SheetStatus.RETURNED
    sheet.returned_at = timezone.now()
    sheet.returned_by = user
    sheet.return_note = note
    sheet.save(update_fields=["status", "returned_at", "returned_by", "return_note", "updated_at"])
    if class_result.status == ClassResultStatus.IN_REVIEW:
        class_result.status = ClassResultStatus.OPEN
        class_result.save(update_fields=["status", "updated_at"])
    return sheet


# ---------------------------------------------------------------------------
# Class workflow
# ---------------------------------------------------------------------------
def _require(class_result, *statuses):
    if class_result.status not in statuses:
        allowed = ", ".join(ClassResultStatus(s).label.lower() for s in statuses)
        raise WorkflowError(f"Results are {class_result.get_status_display().lower()}; this needs them to be {allowed}.")


@transaction.atomic
def begin_review(class_result, user) -> ClassResult:
    class_result = ClassResult.objects.select_for_update().get(pk=class_result.pk)
    _require(class_result, ClassResultStatus.OPEN)
    counts = class_result.sheets.aggregate(total=Count("id"), submitted=Count("id", filter=Q(status=SheetStatus.SUBMITTED)))
    if counts["total"] == 0:
        raise ValidationError("This class has no score sheets. Assign subject teachers and run results setup.")
    if counts["submitted"] < counts["total"]:
        raise ValidationError(f"{counts['total'] - counts['submitted']} of {counts['total']} subject sheets are not submitted yet.")
    compute_summaries(class_result)
    class_result.status = ClassResultStatus.IN_REVIEW
    class_result.review_started_by = user
    class_result.review_started_at = timezone.now()
    class_result.save(update_fields=["status", "review_started_by", "review_started_at", "updated_at"])
    return class_result


@transaction.atomic
def approve(class_result, user) -> ClassResult:
    class_result = ClassResult.objects.select_for_update().get(pk=class_result.pk)
    _require(class_result, ClassResultStatus.IN_REVIEW)
    compute_summaries(class_result)
    class_result.status = ClassResultStatus.APPROVED
    class_result.approved_by = user
    class_result.approved_at = timezone.now()
    class_result.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    return class_result


@transaction.atomic
def send_back(class_result, user) -> ClassResult:
    """Principal moves approved results back to review (e.g. to let the admin return a sheet)."""
    class_result = ClassResult.objects.select_for_update().get(pk=class_result.pk)
    _require(class_result, ClassResultStatus.APPROVED)
    class_result.status = ClassResultStatus.IN_REVIEW
    class_result.approved_by = None
    class_result.approved_at = None
    class_result.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    return class_result


@transaction.atomic
def publish(class_result, user) -> ClassResult:
    class_result = ClassResult.objects.select_for_update().get(pk=class_result.pk)
    _require(class_result, ClassResultStatus.APPROVED)
    compute_summaries(class_result)
    class_result.status = ClassResultStatus.PUBLISHED
    class_result.published_by = user
    class_result.published_at = timezone.now()
    class_result.save(update_fields=["status", "published_by", "published_at", "updated_at"])
    return class_result


@transaction.atomic
def unlock(class_result, user) -> ClassResult:
    class_result = ClassResult.objects.select_for_update().get(pk=class_result.pk)
    _require(class_result, ClassResultStatus.PUBLISHED)
    class_result.status = ClassResultStatus.IN_REVIEW
    class_result.approved_by = None
    class_result.approved_at = None
    class_result.published_by = None
    class_result.published_at = None
    class_result.save(update_fields=["status", "approved_by", "approved_at", "published_by", "published_at", "updated_at"])
    return class_result


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------
def competition_rank(values: list[tuple[int, Decimal]]) -> dict[int, int]:
    """Standard competition ranking ("1, 2, 2, 4") on value, highest first."""
    ordered = sorted(values, key=lambda item: item[1], reverse=True)
    positions, previous, position = {}, None, 0
    for index, (key, value) in enumerate(ordered, start=1):
        if value != previous:
            position = index
            previous = value
        positions[key] = position
    return positions


@transaction.atomic
def compute_summaries(class_result) -> list[ResultSummary]:
    """Recalculate every student's total, average and class position. Comments are kept."""
    scores = Score.objects.filter(sheet__class_result=class_result, total__isnull=False).values("student_id", "total")
    totals: dict[int, list[Decimal]] = {}
    for row in scores:
        totals.setdefault(row["student_id"], []).append(row["total"])
    averages = {sid: _q(sum(v) / len(v)) for sid, v in totals.items() if v}
    positions = competition_rank(list(averages.items()))
    class_size = len(averages)
    existing = {s.student_id: s for s in ResultSummary.objects.filter(class_result=class_result)}
    kept = []
    for student_id, values in totals.items():
        summary = existing.pop(student_id, None) or ResultSummary(
            school=class_result.school, class_result=class_result, student_id=student_id
        )
        summary.total = _q(sum(values))
        summary.subjects_count = len(values)
        summary.average = averages[student_id]
        summary.position = positions[student_id]
        summary.class_size = class_size
        summary.save()
        kept.append(summary)
    for stale in existing.values():
        stale.delete()
    class_result.class_average = _q(sum(averages.values()) / len(averages)) if averages else None
    class_result.save(update_fields=["class_average", "updated_at"])
    return kept


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------
def update_comments(summary, user, data: dict) -> ResultSummary:
    class_result = summary.class_result
    if class_result.status == ClassResultStatus.PUBLISHED:
        raise WorkflowError("Results are published. Unlock them to change comments.")
    fields = []
    if "class_teacher_comment" in data:
        if not (user.role == "teacher" and class_result.classroom.class_teacher_id == user.id):
            raise PermissionDenied("Only the class teacher can write the class teacher's comment.")
        summary.class_teacher_comment = data["class_teacher_comment"]
        fields.append("class_teacher_comment")
    if "principal_comment" in data:
        if user.role != "principal":
            raise PermissionDenied("Only the principal can write the principal's comment.")
        summary.principal_comment = data["principal_comment"]
        fields.append("principal_comment")
    if fields:
        summary.save(update_fields=fields + ["updated_at"])
    return summary


# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------
def missing_scores(school, term) -> dict:
    """Sheets that are not yet submitted, with how many students are missing scores."""
    sheets = (
        ScoreSheet.objects.filter(school=school, term=term)
        .exclude(status=SheetStatus.SUBMITTED)
        .select_related("classroom", "subject", "teacher", "class_result")
    )
    items = []
    for sheet in sheets:
        progress = sheet_progress(sheet)
        items.append(
            {
                "sheet": sheet.id,
                "classroom": {"id": sheet.classroom_id, "name": sheet.classroom.name},
                "subject": {"id": sheet.subject_id, "name": sheet.subject.name},
                "teacher": {"id": sheet.teacher_id, "name": sheet.teacher.full_name} if sheet.teacher_id else None,
                "status": sheet.status,
                "students": progress["students"],
                "complete": progress["complete"],
                "missing": progress["missing"],
                "return_note": sheet.return_note if sheet.status == SheetStatus.RETURNED else "",
            }
        )
    total = ScoreSheet.objects.filter(school=school, term=term).count()
    by_teacher: dict = {}
    for item in items:
        key = item["teacher"]["id"] if item["teacher"] else None
        entry = by_teacher.setdefault(key, {"teacher": item["teacher"], "pending_sheets": 0})
        entry["pending_sheets"] += 1
    return {
        "term": {"id": term.id, "name": str(term)},
        "sheets_total": total,
        "sheets_submitted": total - len(items),
        "sheets_pending": len(items),
        "by_teacher": sorted(by_teacher.values(), key=lambda e: -e["pending_sheets"]),
        "pending": items,
    }
