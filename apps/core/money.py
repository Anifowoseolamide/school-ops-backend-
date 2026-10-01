"""Money helpers.

All amounts are stored and exchanged as integers in kobo (100 kobo = ₦1).
Never use floats for money.
"""
from decimal import ROUND_HALF_UP, Decimal


def naira_to_kobo(amount) -> int:
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def kobo_to_naira(kobo: int) -> Decimal:
    return (Decimal(int(kobo)) / 100).quantize(Decimal("0.01"))


def format_naira(kobo: int, symbol: str = "₦") -> str:
    value = kobo_to_naira(kobo)
    sign = "-" if value < 0 else ""
    return f"{sign}{symbol}{abs(value):,.2f}"
