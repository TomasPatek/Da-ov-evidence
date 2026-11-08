"""Tax depreciation of tangible assets (zákon č. 586/1992 Sb., §§ 26–32).

* § 26 odst. 2 písm. a): tangible asset = input price above 80 000 Kč, useful life over 1 year.
* § 30: depreciation groups 1–6 with periods 3, 5, 10, 20, 30, 50 years.
* § 31: straight-line depreciation, rates for the first year and the following years.
* § 32: accelerated depreciation with coefficients; year 1 = VC / k1,
  following years = 2 × ZC / (k2 − n), n = years already depreciated.
* Annual depreciation is rounded up to whole crowns.
* § 26 odst. 8: depreciation may be interrupted; the schedule continues afterwards.
* § 26 odst. 7: in the year of disposal half of the annual depreciation may be claimed.

The rounding rule and the half-year rule should be confirmed with a tax advisor
before relying on them for a tax return.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from enum import StrEnum

THRESHOLD = Decimal("80000")
ZDP = "zákon č. 586/1992 Sb."


class Method(StrEnum):
    STRAIGHT = "rovnoměrný"
    ACCELERATED = "zrychlený"


STRAIGHT = Method.STRAIGHT
ACCELERATED = Method.ACCELERATED


@dataclass(frozen=True)
class Group:
    years: int
    first_rate: Decimal  # % in the first year (§ 31)
    rate: Decimal  # % in the following years (§ 31)
    k1: int  # coefficient in the first year (§ 32)
    k2: int  # coefficient in the following years (§ 32)


GROUPS: dict[int, Group] = {
    1: Group(3, Decimal("20"), Decimal("40"), 3, 4),
    2: Group(5, Decimal("11"), Decimal("22.25"), 5, 6),
    3: Group(10, Decimal("5.5"), Decimal("10.5"), 10, 11),
    4: Group(20, Decimal("2.15"), Decimal("5.15"), 20, 21),
    5: Group(30, Decimal("1.4"), Decimal("3.4"), 30, 31),
    6: Group(50, Decimal("1.02"), Decimal("2.02"), 50, 51),
}


class DepreciationError(ValueError):
    """Invalid asset data (Czech message)."""


@dataclass(frozen=True)
class YearRow:
    rok: int
    odpis: Decimal
    zustatkova_cena: Decimal
    preruseno: bool = False
    vyrazeno: bool = False


def _up(value: Decimal) -> Decimal:
    return value.to_integral_value(rounding=ROUND_CEILING)


def schedule(
    price: Decimal,
    group: int,
    method: Method,
    first_year: int,
    interrupted: Collection[int] = (),
    disposal_year: int | None = None,
) -> list[YearRow]:
    """Year-by-year depreciation until the asset is fully depreciated or disposed of."""
    if price <= THRESHOLD:
        raise DepreciationError(
            f"Odpisuje se hmotný majetek se vstupní cenou nad 80 000 Kč (§ 26 {ZDP})."
        )
    if group not in GROUPS:
        raise DepreciationError("Odpisová skupina musí být 1 až 6 (§ 30).")
    g = GROUPS[group]
    rows: list[YearRow] = []
    book = price
    done = 0  # years actually depreciated
    year = first_year
    while book > 0:
        if disposal_year is not None and year > disposal_year:
            break
        if year in interrupted:
            rows.append(YearRow(year, Decimal("0"), book, preruseno=True))
            year += 1
            continue
        if method is Method.STRAIGHT:
            rate = g.first_rate if done == 0 else g.rate
            amount = _up(price * rate / 100)
        else:
            amount = _up(price / g.k1) if done == 0 else _up(2 * book / (g.k2 - done))
        amount = min(amount, book)
        disposed = disposal_year == year
        if disposed:
            amount = _up(amount / 2)
        book -= amount
        done += 1
        rows.append(YearRow(year, amount, book, vyrazeno=disposed))
        if disposed:
            break
        year += 1
    return rows


def depreciation_for_year(
    price: Decimal,
    group: int,
    method: Method,
    first_year: int,
    year: int,
    interrupted: Collection[int] = (),
    disposal_year: int | None = None,
) -> Decimal:
    for row in schedule(price, group, method, first_year, interrupted, disposal_year):
        if row.rok == year:
            return row.odpis
    return Decimal("0")
