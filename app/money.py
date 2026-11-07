"""Money handling: the single place that defines parsing, formatting and rounding.

All monetary amounts are ``Decimal``; floats are rejected. Amounts are rounded to
whole haléře (0.01) using commercial rounding (ROUND_HALF_UP).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

HALER = Decimal("0.01")
ZERO = Decimal("0.00")
ROUNDING = ROUND_HALF_UP

_CSV_AMOUNT_RE = re.compile(r"^-?\d+(,\d{1,2})?$")
_CSV_DECIMAL_RE = re.compile(r"^-?\d+(,\d+)?$")
_USER_AMOUNT_RE = re.compile(r"^-?\d+([.,]\d+)?$")
_NBSP = " "


def _require_decimal(value: object) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"expected Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError("amount must be finite")
    return value


def round_money(value: Decimal) -> Decimal:
    """Round to whole haléře. The only rounding rule for money in the app."""
    return _require_decimal(value).quantize(HALER, rounding=ROUNDING)


def sum_money(values: Iterable[Decimal]) -> Decimal:
    """Sum amounts, rounding each one to haléře first (as printed)."""
    total = ZERO
    for v in values:
        total += round_money(v)
    return total


def parse_csv_amount(text: str) -> Decimal:
    """Parse the CSV storage format ``1234,50`` (no thousands separator)."""
    text = text.strip()
    if not _CSV_AMOUNT_RE.match(text):
        raise ValueError(f"neplatná částka: {text!r}")
    return Decimal(text.replace(",", ".")).quantize(HALER)


def format_csv_amount(value: Decimal) -> str:
    """Format an amount for CSV storage: ``1234,50``. Value must be already rounded."""
    value = _require_decimal(value)
    if value != value.quantize(HALER):
        raise ValueError(f"částka není zaokrouhlena na haléře: {value}")
    return f"{value.quantize(HALER):f}".replace(".", ",")


def parse_csv_decimal(text: str) -> Decimal:
    """Parse a non-money decimal (e.g. quantity) from CSV: ``1,5``."""
    text = text.strip()
    if not _CSV_DECIMAL_RE.match(text):
        raise ValueError(f"neplatné číslo: {text!r}")
    return Decimal(text.replace(",", "."))


def format_csv_decimal(value: Decimal) -> str:
    """Format a non-money decimal for CSV without trailing zeros: ``1,5``."""
    value = _require_decimal(value)
    text = f"{value.normalize():f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def parse_user_amount(text: str) -> Decimal:
    """Parse an amount typed by the user: tolerates spaces and a dot or comma."""
    cleaned = text.strip().replace(" ", "").replace(_NBSP, "")
    if not _USER_AMOUNT_RE.match(cleaned):
        raise ValueError(f"neplatná částka: {text!r}")
    try:
        return round_money(Decimal(cleaned.replace(",", ".")))
    except InvalidOperation as exc:  # pragma: no cover - regex guards this
        raise ValueError(f"neplatná částka: {text!r}") from exc


def format_display_amount(value: Decimal, currency: str = "Kč") -> str:
    """Human-readable amount for UI and PDFs: ``1 234,50 Kč`` (non-breaking spaces)."""
    value = round_money(value)
    sign = "-" if value < 0 else ""
    whole, frac = f"{abs(value):f}".split(".")
    groups: list[str] = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return f"{sign}{_NBSP.join(groups)},{frac}{_NBSP}{currency}"
