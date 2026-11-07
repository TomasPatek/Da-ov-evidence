"""Invoice line and total amounts. Rounding is delegated to ``app.money``."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from app.money import ZERO, round_money, sum_money


def line_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """Quantity times unit price, rounded to haléře (as printed on the line)."""
    if not isinstance(quantity, Decimal) or not isinstance(unit_price, Decimal):
        raise TypeError("quantity and unit price must be Decimal")
    return round_money(quantity * unit_price)


def invoice_total(line_totals: Iterable[Decimal]) -> Decimal:
    """Sum of already rounded line totals. A non-VAT invoice has no tax lines."""
    total = sum_money(line_totals)
    if total <= ZERO:
        raise ValueError("celková částka faktury musí být kladná")
    return total
