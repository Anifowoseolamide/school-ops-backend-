"""Report card PDFs: one page per student, generated for one student or a whole class."""
from collections import defaultdict
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.db.models import Avg, Max
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.attendance.services import bulk_attendance_counts
from apps.core import pdf as base
from apps.core.links import make_link_token
from apps.schools.models import GradeBand

from .models import ResultSummary, Score


def ordinal(n: int | None) -> str:
    if not n:
        return "-"
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _fmt(value) -> str:
    if value is None:
        return "-"
    value = Decimal(value)
    return f"{value:.0f}" if value == value.to_integral() else f"{value:.1f}"


def build_report_data(summaries: list[ResultSummary]) -> list[dict]:
    """Collect everything the PDF needs in a handful of queries."""
    if not summaries:
        return []
    class_result = summaries[0].class_result
    school = class_result.school
    term = class_result.term
    student_ids = [s.student_id for s in summaries]

    scores = (
        Score.objects.filter(sheet__class_result=class_result, student_id__in=student_ids)
        .select_related("sheet__subject")
        .order_by("sheet__subject__name")
    )
    by_student = defaultdict(list)
    for score in scores:
        by_student[score.student_id].append(score)
    subject_stats = {
        row["sheet__subject_id"]: row
        for row in Score.objects.filter(sheet__class_result=class_result, total__isnull=False)
        .values("sheet__subject_id")
        .annotate(avg=Avg("total"), high=Max("total"))
    }
    attendance = bulk_attendance_counts(student_ids, term)
    bands = list(GradeBand.objects.filter(school=school).order_by("-min_score"))

    data = []
    for summary in summaries:
        student = summary.student
        att = attendance.get(student.id, {"days": 0, "attended": 0})
        data.append(
            {
                "summary": summary,
                "student": student,
                "classroom": class_result.classroom,
                "term": term,
                "school": school,
                "class_result": class_result,
                "attendance": att,
                "bands": bands,
                "subjects": [
                    {
                        "name": s.sheet.subject.name,
                        "ca1": s.ca1,
                        "ca2": s.ca2,
                        "exam": s.exam,
                        "total": s.total,
                        "grade": s.grade,
                        "remark": s.remark,
                        "class_avg": subject_stats.get(s.sheet.subject_id, {}).get("avg"),
                        "highest": subject_stats.get(s.sheet.subject_id, {}).get("high"),
                    }
                    for s in by_student.get(student.id, [])
                ],
            }
        )
    return data


def _watermark(text):
    def draw(canvas, doc):
        if not text:
            return
        canvas.saveState()
        canvas.setFont(base.FONT_BOLD, 46)
        canvas.setFillColorRGB(0.85, 0.2, 0.2, alpha=0.12)
        canvas.translate(A4[0] / 2, A4[1] / 2)
        canvas.rotate(35)
        canvas.drawCentredString(0, 0, text)
        canvas.restoreState()

    return draw


def _page(item, s, width, school_settings):
    story = []
    school, student, summary = item["school"], item["student"], item["summary"]
    classroom, term, class_result = item["classroom"], item["term"], item["class_result"]

    header = Table(
        [[Paragraph(school.name.upper(), s["title"])],
         [Paragraph(" · ".join(p for p in [school.address, school.phone, school.email] if p) or "&nbsp;", s["subtitle"])],
         [Paragraph(f"<i>{school.motto}</i>" if school.motto else "&nbsp;", s["subtitle"])],
         [Paragraph(f"TERMINAL REPORT CARD &nbsp;·&nbsp; {term}", s["value"])]],
        colWidths=[width],
    )
    header.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LINEBELOW", (0, -1), (-1, -1), 1.4, base.TEAL),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 7),
    ]))
    story += [header, Spacer(1, 6)]

    att = item["attendance"]
    info = [
        ("Name", student.full_name, "Class", classroom.name),
        ("Admission no", student.admission_number, "Gender", student.get_gender_display() if student.gender else "-"),
        ("Attendance", f"{att['attended']} of {att['days']} days" if att["days"] else "-",
         "Students in class", str(summary.class_size or "-")),
    ]
    info_rows = [[Paragraph(a, s["label"]), Paragraph(b, s["bold"]), Paragraph(c, s["label"]), Paragraph(d, s["bold"])] for a, b, c, d in info]
    t = Table(info_rows, colWidths=[width * 0.16, width * 0.38, width * 0.18, width * 0.28])
    t.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [t, Spacer(1, 6)]

    ca1h = f"CA1 ({school_settings.ca1_max})"
    ca2h = f"CA2 ({school_settings.ca2_max})"
    examh = f"Exam ({school_settings.exam_max})"
    headers = ["Subject", ca1h, ca2h, examh, "Total (100)", "Grade", "Remark", "Class avg", "Highest"]
    rows = [[Paragraph(h, s["th"]) for h in headers]]
    for sub in item["subjects"]:
        rows.append([
            Paragraph(sub["name"], s["td"]),
            _fmt(sub["ca1"]), _fmt(sub["ca2"]), _fmt(sub["exam"]),
            Paragraph(f"<b>{_fmt(sub['total'])}</b>", s["td"]),
            Paragraph(f"<b>{sub['grade'] or '-'}</b>", s["td"]),
            Paragraph(sub["remark"] or "-", s["td"]),
            _fmt(sub["class_avg"]), _fmt(sub["highest"]),
        ])
    widths = [0.23, 0.08, 0.08, 0.085, 0.09, 0.08, 0.125, 0.11, 0.12]
    subjects = Table(rows, colWidths=[width * w for w in widths], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), base.TEAL_LIGHT),
        ("FONTNAME", (0, 1), (-1, -1), base.FONT),
        ("FONTSIZE", (0, 1), (-1, -1), 8.3),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, base.LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]
    for i in range(2, len(rows), 2):
        style.append(("BACKGROUND", (0, i), (-1, i), base.ZEBRA))
    subjects.setStyle(TableStyle(style))
    story += [subjects, Spacer(1, 8)]

    stats = Table(
        [[Paragraph(x, s["label"]) for x in ["Total score", "Average", "Position", "Class average"]],
         [Paragraph(_fmt(summary.total), s["value"]), Paragraph(f"{summary.average or 0:.2f}", s["value"]),
          Paragraph(f"{ordinal(summary.position)} of {summary.class_size}", s["value"]),
          Paragraph(f"{class_result.class_average or 0:.2f}", s["value"])]],
        colWidths=[width / 4] * 4,
    )
    stats.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), base.BLUE_LIGHT), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                               ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [stats, Spacer(1, 10)]

    story.append(Paragraph("Class teacher's comment", s["label"]))
    story.append(Paragraph(summary.class_teacher_comment or "&nbsp;", s["italic"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Principal's comment", s["label"]))
    story.append(Paragraph(summary.principal_comment or "&nbsp;", s["italic"]))
    story.append(Spacer(1, 22))

    signatures = Table(
        [["", "", ""], [Paragraph("Class teacher", s["label"]), "", Paragraph("Principal", s["label"])]],
        colWidths=[width * 0.4, width * 0.2, width * 0.4],
    )
    signatures.setStyle(TableStyle([("LINEABOVE", (0, 1), (0, 1), 0.6, base.LINE), ("LINEABOVE", (2, 1), (2, 1), 0.6, base.LINE),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [signatures, Spacer(1, 10)]

    key = " | ".join(f"{b.grade} {int(b.min_score)}-{int(b.max_score)}" for b in item["bands"])
    story.append(Paragraph(f"Grading: {key}", s["small"]))
    if class_result.next_term_begins:
        story.append(Paragraph(f"Next term begins: {class_result.next_term_begins:%d %B %Y}", s["small"]))
    if school_settings.report_card_footer:
        story.append(Paragraph(school_settings.report_card_footer, s["small"]))
    return story


def render_report_cards(summaries: list[ResultSummary], *, draft: bool = False) -> bytes:
    base.register_fonts()
    s = base.styles()
    items = build_report_data(summaries)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=13 * mm,
                            bottomMargin=13 * mm, title="Report cards")
    width = A4[0] - 30 * mm
    story = []
    if items:
        school_settings = items[0]["school"].settings
        for index, item in enumerate(items):
            if index:
                story.append(PageBreak())
            story += _page(item, s, width, school_settings)
    else:
        story.append(Paragraph("No results to show.", s["body"]))
    mark = _watermark("DRAFT - NOT PUBLISHED" if draft else None)
    doc.build(story, onFirstPage=mark, onLaterPages=mark)
    return buffer.getvalue()


def report_card_link(summary) -> str:
    return f"{settings.BACKEND_URL}/api/v1/public/report-cards/{make_link_token('report_card', summary.id)}/"
