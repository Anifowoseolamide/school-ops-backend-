from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.schools.services import term_for_date
from apps.students.models import Student, StudentStatus

from .models import ATTENDED, AttendanceRecord, AttendanceStatus


def class_register(classroom, day):
    """Return (students, records_by_student_id) for a class on a day."""
    students = list(
        Student.objects.filter(classroom=classroom, status=StudentStatus.ACTIVE).order_by("last_name", "first_name")
    )
    records = {
        r.student_id: r
        for r in AttendanceRecord.objects.filter(classroom=classroom, date=day).select_related("marked_by")
    }
    return students, records


@transaction.atomic
def save_register(classroom, day, entries: dict, user):
    """Save a full register. `entries` maps student_id -> (status, note).

    Students not in `entries` are marked present, so a teacher only has to tick
    the absent and late ones.
    """
    term = term_for_date(classroom.school, day)
    students, existing = class_register(classroom, day)
    saved = []
    for student in students:
        status, note = entries.get(student.id, (AttendanceStatus.PRESENT, ""))
        record = existing.get(student.id)
        if record is None:
            record = AttendanceRecord(
                school=classroom.school, student=student, classroom=classroom, term=term, date=day
            )
        record.status = status
        record.note = note or ""
        record.marked_by = user
        record.classroom = classroom
        record.term = term
        record.save()
        saved.append(record)
    return term, saved


def summary_for_day(school, day, classroom_ids=None):
    """Per-class counts for one day, including classes not yet marked."""
    from apps.schools.models import ClassRoom

    classes = ClassRoom.objects.filter(school=school).select_related("class_teacher").annotate(
        active_students=Count("students", filter=Q(students__status=StudentStatus.ACTIVE), distinct=True)
    )
    if classroom_ids is not None:
        classes = classes.filter(id__in=classroom_ids)
    counts = {
        row["classroom_id"]: row
        for row in AttendanceRecord.objects.filter(school=school, date=day)
        .values("classroom_id")
        .annotate(
            marked=Count("id"),
            present=Count("id", filter=Q(status=AttendanceStatus.PRESENT)),
            late=Count("id", filter=Q(status=AttendanceStatus.LATE)),
            absent=Count("id", filter=Q(status=AttendanceStatus.ABSENT)),
            excused=Count("id", filter=Q(status=AttendanceStatus.EXCUSED)),
        )
    }
    rows = []
    totals = {"students": 0, "marked": 0, "attended": 0, "absent": 0, "late": 0, "excused": 0}
    for c in classes:
        row = counts.get(c.id, {})
        marked = row.get("marked", 0)
        attended = row.get("present", 0) + row.get("late", 0)
        rows.append(
            {
                "classroom": {"id": c.id, "name": c.name},
                "class_teacher": c.class_teacher.full_name if c.class_teacher_id else None,
                "students": c.active_students,
                "is_marked": marked > 0,
                "present": row.get("present", 0),
                "late": row.get("late", 0),
                "absent": row.get("absent", 0),
                "excused": row.get("excused", 0),
                "attendance_rate": round(attended * 100 / marked, 1) if marked else None,
            }
        )
        totals["students"] += c.active_students
        totals["marked"] += marked
        totals["attended"] += attended
        totals["absent"] += row.get("absent", 0)
        totals["late"] += row.get("late", 0)
        totals["excused"] += row.get("excused", 0)
    totals["attendance_rate"] = round(totals["attended"] * 100 / totals["marked"], 1) if totals["marked"] else None
    totals["classes_marked"] = sum(1 for r in rows if r["is_marked"])
    totals["classes_total"] = len(rows)
    return {"date": day.isoformat(), "totals": totals, "classes": rows}


def student_attendance_summary(student, term) -> dict:
    qs = AttendanceRecord.objects.filter(student=student, term=term)
    counts = qs.aggregate(
        days=Count("id"),
        present=Count("id", filter=Q(status=AttendanceStatus.PRESENT)),
        late=Count("id", filter=Q(status=AttendanceStatus.LATE)),
        absent=Count("id", filter=Q(status=AttendanceStatus.ABSENT)),
        excused=Count("id", filter=Q(status=AttendanceStatus.EXCUSED)),
    )
    counts["attended"] = counts["present"] + counts["late"]
    counts["attendance_rate"] = round(counts["attended"] * 100 / counts["days"], 1) if counts["days"] else None
    return counts


def bulk_attendance_counts(student_ids, term) -> dict[int, dict]:
    """{student_id: {"days": n, "attended": m}} for report cards."""
    rows = (
        AttendanceRecord.objects.filter(student_id__in=student_ids, term=term)
        .values("student_id")
        .annotate(days=Count("id"), attended=Count("id", filter=Q(status__in=ATTENDED)))
    )
    return {r["student_id"]: {"days": r["days"], "attended": r["attended"]} for r in rows}


def today():
    return timezone.localdate()
