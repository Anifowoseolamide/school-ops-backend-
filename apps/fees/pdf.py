"""Payment receipt PDF."""
from io import BytesIO

from django.utils import timezone
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.core import pdf as base


def render_receipt(receipt) -> bytes:
    base.register_fonts()
    s = base.styles()
    payment = receipt.payment
    invoice = payment.invoice
    student = payment.student
    school = receipt.school

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A5, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
        title=f"Receipt {receipt.number}", author=school.name,
    )
    width = A5[0] - 24 * mm
    story = []

    contact = " · ".join(p for p in [school.address, school.phone, school.email] if p) or "&nbsp;"
    header = Table(
        [[Paragraph(school.name, s["title"]), ""],
         [Paragraph(contact, s["subtitle"]), Paragraph(f"PAYMENT RECEIPT<br/>{receipt.number}", s["value_right"])]],
        colWidths=[width * 0.6, width * 0.4],
    )
    header.setStyle(TableStyle([
        ("SPAN", (0, 0), (1, 0)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 1), (1, 1), "RIGHT"),
        ("LINEBELOW", (0, -1), (-1, -1), 1.2, base.TEAL),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story += [header, Spacer(1, 8)]

    local_issued = timezone.localtime(receipt.issued_at)
    details = [
        ("Date", local_issued.strftime("%d %b %Y, %H:%M")),
        ("Student", f"{student.full_name} ({student.admission_number})"),
        ("Class", invoice.classroom.name if invoice.classroom_id else "-"),
        ("Term", str(invoice.term)),
        ("Invoice", invoice.number),
        ("Payment method", payment.get_method_display() + (f" ({payment.channel})" if payment.channel else "")),
        ("Reference", payment.external_reference or payment.reference),
    ]
    if payment.payer_name:
        details.append(("Paid by", payment.payer_name))
    rows = [[Paragraph(k, s["label"]), Paragraph(v, s["body"])] for k, v in details]
    t = Table(rows, colWidths=[width * 0.3, width * 0.7])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, base.LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story += [t, Spacer(1, 10)]

    amounts = Table(
        [
            [Paragraph("Amount paid", s["label"]), Paragraph("Invoice total", s["label"]), Paragraph("Balance after this payment", s["label"])],
            [Paragraph(base.money(receipt.amount_kobo), s["value"]), Paragraph(base.money(invoice.total_kobo), s["bold"]),
             Paragraph(base.money(receipt.balance_after_kobo), s["bold"])],
        ],
        colWidths=[width / 3] * 3,
    )
    amounts.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), base.TEAL_LIGHT),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [amounts, Spacer(1, 14)]
    if payment.is_reversed:
        story.append(Paragraph("<b>This payment has been reversed.</b>", s["body"]))
    story.append(Paragraph(
        "This receipt was generated electronically and is valid without a signature. "
        "Keep it for your records.", s["small"],
    ))
    doc.build(story)
    return buffer.getvalue()
