"""Data for the four role dashboards. Each function returns plain JSON-ready dicts."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, F, Max, Q, Sum
from django.utils import timezone

from apps.attendance.models import AttendanceRecord
from apps.attendance.services import summary_for_day
from apps.audit.models import AuditLog
from apps.core.roles import ADMIN, BURSAR, PRINCIPAL, TEACHER
from apps.fees.models import Invoice, InvoiceStatus, Payment, PaymentMethod, PaymentStatus
from apps.fees.services import collections_summary, outstanding_by_class
from apps.results.models import ClassResult, ClassResultStatus, ResultSummary, ScoreSheet, SheetStatus
from apps.results.services import missing_scores, sheet_progress
from apps.schools.models import ClassRoom, TeacherAssignment
from apps.schools.services import get_current_term
from apps.students.models import Student, StudentImport, StudentStatus

User = get_user_model()


def _term_info(term):
    return {"id": term.id, "name": str(term), "start_date": term.start_date, "end_date": term.end_date} if term else None


def _is_school_day(term, day) -> bool:
    return bool(term and term.contains(day) and day.weekday() < 5)


def _recent_payments(school, limit=8):
    payments = (
        Payment.objects.filter(school=school, status=PaymentStatus.SUCCESSFUL)
        .select_related("student", "invoice__classroom")
        .order_by("-paid_at")[:limit]
    )
    return [
        {
            "id": p.id,
            "student": p.student.full_name,
            "classroom": p.invoice.classroom.name if p.invoice.classroom_id else None,
            "amount_kobo": p.amount_kobo,
            "method": p.method,
            "paid_at": p.paid_at,
        }
        for p in payments
    ]


def _results_progress(school, term):
    if term is None:
        return None
    sheets = ScoreSheet.objects.filter(school=school, term=term).aggregate(
        total=Count("id"), submitted=Count("id", filter=Q(status=SheetStatus.SUBMITTED))
    )
    by_status = dict(
        ClassResult.objects.filter(school=school, term=term).values_list("status").annotate(n=Count("id"))
    )
    return {
        "sheets_total": sheets["total"],
        "sheets_submitted": sheets["submitted"],
        "sheets_pending": sheets["total"] - sheets["submitted"],
        "class_results": {status: by_status.get(status, 0) for status in ClassResultStatus.values},
    }


def principal_dashboard(school) -> dict:
    term = get_current_term(school, required=False)
    today = timezone.localdate()

    students = Student.objects.filter(school=school, status=StudentStatus.ACTIVE).count()
    staff_by_role = dict(
        User.objects.filter(school=school, is_active=True).values_list("role").annotate(n=Count("id"))
    )
    classes = ClassRoom.objects.filter(school=school).count()

    fees = outstanding_by_class(school, term) if term else None
    attendance = summary_for_day(school, today) if term else None
    results = _results_progress(school, term)

    attention = []
    if term:
        missing = missing_scores(school, term)
        teachers_pending = [t for t in missing["by_teacher"] if t["teacher"]]
        if teachers_pending:
            attention.append({
                "severity": "high",
                "type": "scores_missing",
                "message": f"{len(teachers_pending)} teacher(s) have {missing['sheets_pending']} score sheet(s) not submitted",
                "count": missing["sheets_pending"],
                "link": {"endpoint": "/api/v1/results/missing/", "params": {"term": term.id}},
            })
        awaiting = ClassResult.objects.filter(school=school, term=term, status=ClassResultStatus.IN_REVIEW).count()
        if awaiting:
            attention.append({
                "severity": "medium",
                "type": "results_awaiting_approval",
                "message": f"{awaiting} class result(s) waiting for your approval",
                "count": awaiting,
                "link": {"endpoint": "/api/v1/results/class-results/", "params": {"term": term.id, "status": "in_review"}},
            })
        approved = ClassResult.objects.filter(school=school, term=term, status=ClassResultStatus.APPROVED).count()
        if approved:
            attention.append({
                "severity": "low",
                "type": "results_ready_to_publish",
                "message": f"{approved} approved class result(s) ready to publish",
                "count": approved,
                "link": {"endpoint": "/api/v1/results/class-results/", "params": {"term": term.id, "status": "approved"}},
            })
        heavy_debtors = Invoice.objects.filter(school=school, term=term, total_kobo__gt=0).exclude(
            status=InvoiceStatus.CANCELLED
        ).filter(balance_kobo__gt=F("total_kobo") / 2).count()
        if heavy_debtors:
            attention.append({
                "severity": "high",
                "type": "students_owing",
                "message": f"{heavy_debtors} student(s) owe more than half of this term's fees",
                "count": heavy_debtors,
                "link": {"endpoint": "/api/v1/fees/invoices/", "params": {"term": term.id, "has_balance": "true",
                                                                          "ordering": "-balance_kobo"}},
            })
        if _is_school_day(term, today) and attendance:
            unmarked = [c for c in attendance["classes"] if not c["is_marked"] and c["students"]]
            if unmarked:
                attention.append({
                    "severity": "medium",
                    "type": "attendance_not_marked",
                    "message": f"{len(unmarked)} class(es) have not marked attendance today",
                    "count": len(unmarked),
                    "classes": [c["classroom"]["name"] for c in unmarked],
                    "link": {"endpoint": "/api/v1/attendance/summary/", "params": {"date": today.isoformat()}},
                })
    else:
        attention.append({"severity": "high", "type": "no_current_term",
                          "message": "No current term is set. Ask the admin to set it.", "count": 1, "link": None})

    last_actions = dict(
        AuditLog.objects.filter(school=school, actor__isnull=False)
        .values_list("actor_id")
        .annotate(last=Max("created_at"))
    )
    staff = User.objects.filter(school=school, is_active=True).order_by("first_name")
    staff_activity = sorted(
        [
            {
                "id": u.id,
                "name": u.full_name,
                "role": u.role,
                "last_login": u.last_login,
                "last_activity": last_actions.get(u.id),
            }
            for u in staff
        ],
        key=lambda r: (r["last_activity"] is None, -(r["last_activity"].timestamp() if r["last_activity"] else 0)),
    )

    severity_order = {"high": 0, "medium": 1, "low": 2}
    attention.sort(key=lambda a: severity_order.get(a["severity"], 3))
    return {
        "term": _term_info(term),
        "counts": {
            "students": students,
            "staff": sum(staff_by_role.values()),
            "staff_by_role": {r: staff_by_role.get(r, 0) for r in (PRINCIPAL, ADMIN, BURSAR, TEACHER)},
            "classes": classes,
        },
        "fees": fees,
        "attendance_today": attendance["totals"] if attendance else None,
        "results": results,
        "needs_attention": attention,
        "recent_payments": _recent_payments(school),
        "staff_activity": staff_activity,
    }


def bursar_dashboard(school) -> dict:
    term = get_current_term(school, required=False)
    today = timezone.localdate()
    successful = Payment.objects.filter(school=school, status=PaymentStatus.SUCCESSFUL)

    def window(start):
        agg = successful.filter(paid_at__date__gte=start, paid_at__date__lte=today).aggregate(
            amount=Sum("amount_kobo"), count=Count("id")
        )
        return {"amount_kobo": agg["amount"] or 0, "count": agg["count"]}

    top_debtors = []
    fees = None
    if term:
        fees = outstanding_by_class(school, term)
        top_debtors = [
            {
                "invoice": inv.id,
                "number": inv.number,
                "student": inv.student.full_name,
                "admission_number": inv.student.admission_number,
                "classroom": inv.classroom.name if inv.classroom_id else None,
                "total_kobo": inv.total_kobo,
                "balance_kobo": inv.balance_kobo,
                "status": inv.status,
            }
            for inv in Invoice.objects.filter(school=school, term=term, balance_kobo__gt=0)
            .exclude(status=InvoiceStatus.CANCELLED)
            .select_related("student", "classroom")
            .order_by("-balance_kobo")[:10]
        ]
    pending_online = Payment.objects.filter(
        school=school, method=PaymentMethod.PAYSTACK, status=PaymentStatus.PENDING,
        created_at__gte=timezone.now() - timedelta(days=2),
    ).count()
    return {
        "term": _term_info(term),
        "today": window(today),
        "this_week": window(today - timedelta(days=today.weekday())),
        "this_month": collections_summary(school, today.replace(day=1), today),
        "fees": fees,
        "top_debtors": top_debtors,
        "pending_online_payments": pending_online,
        "recent_payments": _recent_payments(school, limit=10),
    }


def admin_dashboard(school) -> dict:
    term = get_current_term(school, required=False)
    session = term.session if term else None
    students = Student.objects.filter(school=school).aggregate(
        active=Count("id", filter=Q(status=StudentStatus.ACTIVE)),
        unassigned=Count("id", filter=Q(status=StudentStatus.ACTIVE, classroom__isnull=True)),
    )
    classes = ClassRoom.objects.filter(school=school)
    no_teacher = [c.name for c in classes.filter(class_teacher__isnull=True)]
    no_assignments = []
    if session:
        assigned = set(TeacherAssignment.objects.filter(school=school, session=session).values_list("classroom_id", flat=True))
        no_assignments = [c.name for c in classes if c.id not in assigned]

    results = _results_progress(school, term)
    ready_for_review = []
    returned_sheets = 0
    if term:
        for cr in ClassResult.objects.filter(school=school, term=term, status=ClassResultStatus.OPEN).annotate(
            total=Count("sheets"), submitted=Count("sheets", filter=Q(sheets__status=SheetStatus.SUBMITTED))
        ).select_related("classroom"):
            if cr.total and cr.total == cr.submitted:
                ready_for_review.append({"class_result": cr.id, "classroom": cr.classroom.name})
        returned_sheets = ScoreSheet.objects.filter(school=school, term=term, status=SheetStatus.RETURNED).count()

    recent_changes = [
        {"action": a.action, "object": a.object_repr, "by": a.actor_email, "at": a.created_at}
        for a in AuditLog.objects.filter(school=school, action__startswith="student").order_by("-created_at")[:10]
    ]
    imports = [
        {"id": i.id, "file": i.original_filename, "status": i.status, "created": i.created_count, "at": i.created_at}
        for i in StudentImport.objects.filter(school=school).order_by("-created_at")[:5]
    ]
    return {
        "term": _term_info(term),
        "counts": {
            "students": students["active"],
            "students_without_class": students["unassigned"],
            "classes": classes.count(),
            "staff": User.objects.filter(school=school, is_active=True).count(),
        },
        "setup_gaps": {"classes_without_class_teacher": no_teacher, "classes_without_subject_teachers": no_assignments},
        "results": results,
        "ready_for_review": ready_for_review,
        "returned_sheets": returned_sheets,
        "recent_student_changes": recent_changes,
        "recent_imports": imports,
    }


def teacher_dashboard(user) -> dict:
    school = user.school
    term = get_current_term(school, required=False)
    today = timezone.localdate()
    form_classes = list(ClassRoom.objects.filter(school=school, class_teacher=user))
    marked_today = set(
        AttendanceRecord.objects.filter(school=school, date=today, classroom__in=form_classes)
        .values_list("classroom_id", flat=True)
        .distinct()
    )
    teaching = []
    if term:
        teaching = [
            {"classroom": {"id": a.classroom_id, "name": a.classroom.name}, "subject": {"id": a.subject_id, "name": a.subject.name}}
            for a in TeacherAssignment.objects.filter(school=school, teacher=user, session=term.session)
            .select_related("classroom", "subject")
        ]
    sheets = []
    if term:
        for sheet in ScoreSheet.objects.filter(school=school, term=term, teacher=user).select_related(
            "classroom", "subject", "class_result"
        ):
            sheets.append({
                "sheet": sheet.id,
                "classroom": sheet.classroom.name,
                "subject": sheet.subject.name,
                "status": sheet.status,
                "class_result_status": sheet.class_result.status,
                "progress": sheet_progress(sheet),
                "return_note": sheet.return_note if sheet.status == SheetStatus.RETURNED else "",
            })
    comments_pending = 0
    if term and form_classes:
        comments_pending = ResultSummary.objects.filter(
            class_result__term=term,
            class_result__classroom__in=form_classes,
            class_result__status__in=[ClassResultStatus.IN_REVIEW, ClassResultStatus.APPROVED],
            class_teacher_comment="",
        ).count()
    return {
        "term": _term_info(term),
        "form_classes": [
            {
                "id": c.id,
                "name": c.name,
                "students": c.students.filter(status=StudentStatus.ACTIVE).count(),
                "attendance_marked_today": c.id in marked_today,
            }
            for c in form_classes
        ],
        "attendance_to_mark": [
            {"id": c.id, "name": c.name} for c in form_classes
            if c.id not in marked_today and _is_school_day(term, today)
        ],
        "teaching": teaching,
        "score_sheets": sheets,
        "sheets_to_finish": sum(1 for s in sheets if s["status"] != SheetStatus.SUBMITTED),
        "returned_sheets": [s for s in sheets if s["status"] == SheetStatus.RETURNED],
        "comments_pending": comments_pending,
    }
