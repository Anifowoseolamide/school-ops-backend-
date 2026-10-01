"""Shared PDF building blocks (fonts, colours, styles) for receipts and report cards."""
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont

FONT_DIR = Path(__file__).resolve().parent / "fonts"

NAVY = HexColor("#12304A")
TEAL = HexColor("#0E8A7D")
AMBER = HexColor("#D9930D")
RED = HexColor("#C0392B")
GREEN = HexColor("#2E8B57")
INK = HexColor("#1F2933")
MUTED = HexColor("#5F6B7A")
LINE = HexColor("#C9D1DA")
ZEBRA = HexColor("#F4F6F8")
TEAL_LIGHT = HexColor("#DDF1EE")
BLUE_LIGHT = HexColor("#E1ECF7")

_fonts_registered = False
FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_ITALIC = "Helvetica-Oblique"
CURRENCY_SYMBOL = "NGN "


def register_fonts():
    """Register DejaVu fonts (they include the ₦ sign). Falls back to Helvetica."""
    global _fonts_registered, FONT, FONT_BOLD, FONT_ITALIC, CURRENCY_SYMBOL
    if _fonts_registered:
        return
    try:
        pdfmetrics.registerFont(TTFont("DejaVu", str(FONT_DIR / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Oblique", str(FONT_DIR / "DejaVuSans-Oblique.ttf")))
        # Lets <b> and <i> tags inside Paragraphs switch to the bold/oblique files.
        registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold", italic="DejaVu-Oblique", boldItalic="DejaVu-Bold")
        FONT, FONT_BOLD, FONT_ITALIC = "DejaVu", "DejaVu-Bold", "DejaVu-Oblique"
        CURRENCY_SYMBOL = "₦"
    except Exception:  # pragma: no cover - font files missing
        pass
    _fonts_registered = True


def styles() -> dict:
    register_fonts()
    return {
        "title": ParagraphStyle("title", fontName=FONT_BOLD, fontSize=15, leading=19, textColor=NAVY),
        "subtitle": ParagraphStyle("subtitle", fontName=FONT, fontSize=9, leading=12, textColor=MUTED),
        "body": ParagraphStyle("body", fontName=FONT, fontSize=9, leading=12.5, textColor=INK),
        "bold": ParagraphStyle("bold", fontName=FONT_BOLD, fontSize=9, leading=12.5, textColor=INK),
        "small": ParagraphStyle("small", fontName=FONT, fontSize=7.5, leading=10, textColor=MUTED),
        "label": ParagraphStyle("label", fontName=FONT, fontSize=7.5, leading=10, textColor=MUTED),
        "value": ParagraphStyle("value", fontName=FONT_BOLD, fontSize=10, leading=13, textColor=NAVY),
        "value_right": ParagraphStyle("value_right", fontName=FONT_BOLD, fontSize=10, leading=13, textColor=NAVY,
                                      alignment=2),
        "italic": ParagraphStyle("italic", fontName=FONT_ITALIC, fontSize=8.5, leading=12, textColor=INK),
        "th": ParagraphStyle("th", fontName=FONT_BOLD, fontSize=8, leading=10.5, textColor=NAVY),
        "td": ParagraphStyle("td", fontName=FONT, fontSize=8.3, leading=11, textColor=INK),
    }


def money(kobo: int) -> str:
    register_fonts()
    value = int(kobo) / 100
    sign = "-" if value < 0 else ""
    return f"{sign}{CURRENCY_SYMBOL}{abs(value):,.2f}"
