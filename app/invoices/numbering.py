"""Gap-free invoice number series ``RRRRNNNN`` (year + sequence).

The invoice number is also the variable symbol (VS) of the payment.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.config import INVOICE_NUMBER_FORMATS


class NumberingError(ValueError):
    """Invalid number, unknown format or exhausted series."""


def _seq_width(fmt: str) -> int:
    if fmt not in INVOICE_NUMBER_FORMATS:
        raise NumberingError(f"neznámý formát číselné řady: {fmt}")
    return fmt.count("N")


def format_number(year: int, seq: int, fmt: str) -> str:
    width = _seq_width(fmt)
    if not 1 <= seq < 10**width:
        raise NumberingError(f"pořadové číslo {seq} se nevejde do formátu {fmt}")
    if not 1000 <= year <= 9999:
        raise NumberingError(f"neplatný rok {year}")
    return f"{year:04d}{seq:0{width}d}"


def parse_number(number: str, fmt: str) -> tuple[int, int]:
    width = _seq_width(fmt)
    if not re.fullmatch(rf"\d{{{4 + width}}}", number):
        raise NumberingError(f"číslo faktury {number!r} neodpovídá formátu {fmt}")
    year, seq = int(number[:4]), int(number[4:])
    if seq == 0:
        raise NumberingError(f"číslo faktury {number!r} má nulové pořadí")
    return year, seq


def next_number(existing: Iterable[str], year: int, fmt: str, start: int) -> str:
    """Next number of ``year``: highest existing + 1, or ``start`` for an empty year."""
    seqs = []
    for number in existing:
        y, seq = parse_number(number, fmt)
        if y == year:
            seqs.append(seq)
    return format_number(year, max(seqs) + 1 if seqs else start, fmt)
