from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from .models import AcademicSession, ClassRoom, GradeBand, School, SchoolSettings, TeacherAssignment, Term

# WAEC-style scale. Grades are matched on "total >= min_score" from the top band down.
DEFAULT_GRADE_BANDS = [
    ("A1", "75", "100", "Excellent"),
    ("B2", "70", "74.99", "Very good"),
    ("B3", "65", "69.99", "Good"),
    ("C4", "60", "64.99", "Credit"),
    ("C5", "55", "59.99", "Credit"),
    ("C6", "50", "54.99", "Credit"),
    ("D7", "45", "49.99", "Pass"),
    ("E8", "40", "44.99", "Pass"),
    ("F9", "0", "39.99", "Fail"),
]


@transaction.atomic
def create_school(name: str, slug: str | None = None, **fields) -> School:
    """Create a school with default settings and the default grading scale."""
    base_slug = slugify(slug or name)[:70] or "school"
    candidate, n = base_slug, 2
    while School.objects.filter(slug=candidate).exists():
        candidate, n = f"{base_slug}-{n}", n + 1
    school = School.objects.create(name=name, slug=candidate, **fields)
    SchoolSettings.objects.create(school=school)
    GradeBand.objects.bulk_create(
        [
            GradeBand(school=school, grade=g, min_score=Decimal(lo), max_score=Decimal(hi), remark=r)
            for g, lo, hi, r in DEFAULT_GRADE_BANDS
        ]
    )
    return school


def get_settings(school) -> SchoolSettings:
    settings_obj, _ = SchoolSettings.objects.get_or_create(school=school)
    return settings_obj


def get_current_term(school, required: bool = True) -> Term | None:
    term = (
        Term.objects.filter(school=school, is_current=True).select_related("session").order_by("-start_date").first()
    )
    if term is None and required:
        raise ValidationError({"term": "No current term is set. Ask the admin to set the current term."})
    return term


def get_current_session(school, required: bool = False) -> AcademicSession | None:
    session = AcademicSession.objects.filter(school=school, is_current=True).order_by("-start_date").first()
    if session is None:
        term = get_current_term(school, required=False)
        session = term.session if term else None
    if session is None and required:
        raise ValidationError({"session": "No current academic session is set."})
    return session


def resolve_term(school, term_id=None, required: bool = True) -> Term | None:
    """Return the term with `term_id` (within the school) or the current term."""
    if term_id:
        try:
            return Term.objects.select_related("session").get(school=school, pk=term_id)
        except (Term.DoesNotExist, ValueError, TypeError) as exc:
            raise ValidationError({"term": "Term not found."}) from exc
    return get_current_term(school, required=required)


def term_for_date(school, day) -> Term | None:
    return (
        Term.objects.filter(school=school, start_date__lte=day, end_date__gte=day)
        .select_related("session")
        .order_by("-start_date")
        .first()
    )


@transaction.atomic
def set_current_term(term: Term) -> Term:
    Term.objects.filter(school=term.school).exclude(pk=term.pk).update(is_current=False)
    AcademicSession.objects.filter(school=term.school).exclude(pk=term.session_id).update(is_current=False)
    Term.objects.filter(pk=term.pk).update(is_current=True)
    AcademicSession.objects.filter(pk=term.session_id).update(is_current=True)
    term.refresh_from_db()
    return term


@transaction.atomic
def set_current_session(session: AcademicSession) -> AcademicSession:
    AcademicSession.objects.filter(school=session.school).exclude(pk=session.pk).update(is_current=False)
    AcademicSession.objects.filter(pk=session.pk).update(is_current=True)
    session.refresh_from_db()
    return session


def teacher_classroom_ids(user, session=None) -> set[int]:
    """Classes a teacher may see: classes they are form teacher of, plus classes they teach."""
    if session is None:
        session = get_current_session(user.school)
    condition = Q(class_teacher=user)
    if session is not None:
        condition |= Q(assignments__teacher=user, assignments__session=session)
    return set(ClassRoom.objects.filter(school_id=user.school_id).filter(condition).values_list("id", flat=True))


def teacher_subject_pairs(user, session=None) -> set[tuple[int, int]]:
    """(classroom_id, subject_id) pairs the teacher is assigned to teach."""
    if session is None:
        session = get_current_session(user.school)
    if session is None:
        return set()
    return set(
        TeacherAssignment.objects.filter(school_id=user.school_id, teacher=user, session=session).values_list(
            "classroom_id", "subject_id"
        )
    )


def grade_for(total, bands) -> tuple[str, str]:
    """Return (grade, remark) for a total score using bands ordered high to low."""
    if total is None:
        return "", ""
    for band in bands:
        if Decimal(total) >= band.min_score:
            return band.grade, band.remark
    return "", ""
