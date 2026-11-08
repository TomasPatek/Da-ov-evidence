"""Tax depreciation (§ 31 and § 32 ZDP) against hand-computed tables."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.tax.depreciation import (
    ACCELERATED,
    STRAIGHT,
    DepreciationError,
    Method,
    schedule,
)

D = Decimal


def amounts(price: str, group: int, method: Method, **kw: object) -> list[Decimal]:
    return [row.odpis for row in schedule(D(price), group, method, 2027, **kw)]  # type: ignore[arg-type]


# Hand-computed tables for an input price of 100 000 Kč (odpis rounded up to whole Kč).
STRAIGHT_TABLES = {
    1: ["20000", "40000", "40000"],
    2: ["11000", "22250", "22250", "22250", "22250"],
    3: ["5500"] + ["10500"] * 9,
    4: ["2150"] + ["5150"] * 19,
    5: ["1400"] + ["3400"] * 29,
    6: ["1020"] + ["2020"] * 49,
}

ACCELERATED_TABLES = {
    # year 1: VC / k1; then 2 × ZC / (k2 − n), rounded up
    1: ["33334", "44444", "22222"],
    2: ["20000", "32000", "24000", "16000", "8000"],
    3: ["10000", "18000", "16000", "14000", "12000", "10000", "8000", "6000", "4000", "2000"],
}


@pytest.mark.parametrize("group", sorted(STRAIGHT_TABLES))
def test_straight_line_tables(group: int) -> None:
    result = amounts("100000", group, STRAIGHT)
    assert result == [D(x) for x in STRAIGHT_TABLES[group]]
    assert sum(result) == D("100000")


@pytest.mark.parametrize("group", sorted(ACCELERATED_TABLES))
def test_accelerated_tables(group: int) -> None:
    result = amounts("100000", group, ACCELERATED)
    assert result == [D(x) for x in ACCELERATED_TABLES[group]]
    assert sum(result) == D("100000")


@pytest.mark.parametrize("group", [4, 5, 6])
def test_accelerated_long_groups_sum_up(group: int) -> None:
    result = amounts("1000000", group, ACCELERATED)
    assert len(result) == {4: 20, 5: 30, 6: 50}[group]
    assert sum(result) == D("1000000")
    assert result[0] == (D("1000000") / {4: 20, 5: 30, 6: 50}[group]).to_integral_value(
        rounding="ROUND_CEILING"
    )


def test_rounding_up_to_whole_crowns() -> None:
    # 85 555 × 20 % = 17 111; 85 555 × 40 % = 34 222; last year takes the remainder.
    assert amounts("85555", 1, STRAIGHT) == [D("17111"), D("34222"), D("34222")]
    assert amounts("85001", 2, STRAIGHT)[0] == D("9351")  # 9 350,11 -> 9 351


def test_rows_carry_book_value() -> None:
    rows = schedule(D("100000"), 1, STRAIGHT, 2027)
    assert [(r.rok, r.odpis, r.zustatkova_cena) for r in rows] == [
        (2027, D("20000"), D("80000")),
        (2028, D("40000"), D("40000")),
        (2029, D("40000"), D("0")),
    ]


def test_interruption_shifts_the_schedule() -> None:
    rows = schedule(D("100000"), 1, STRAIGHT, 2027, interrupted={2028})
    assert [(r.rok, r.odpis) for r in rows] == [
        (2027, D("20000")),
        (2028, D("0")),
        (2029, D("40000")),
        (2030, D("40000")),
    ]
    rows = schedule(D("100000"), 1, ACCELERATED, 2027, interrupted={2028})
    assert [(r.rok, r.odpis) for r in rows] == [
        (2027, D("33334")),
        (2028, D("0")),
        (2029, D("44444")),
        (2030, D("22222")),
    ]


def test_disposal_year_gets_half_and_ends_schedule() -> None:
    rows = schedule(D("100000"), 2, STRAIGHT, 2027, disposal_year=2029)
    assert [(r.rok, r.odpis) for r in rows] == [
        (2027, D("11000")),
        (2028, D("22250")),
        (2029, D("11125")),
    ]
    assert rows[-1].vyrazeno and rows[-1].zustatkova_cena == D("55625")


@pytest.mark.parametrize(
    ("price", "group", "message"),
    [("80000", 1, "80 000"), ("100000", 7, "skupina"), ("-1", 1, "80 000")],
)
def test_validation(price: str, group: int, message: str) -> None:
    with pytest.raises(DepreciationError, match=message):
        schedule(D(price), group, STRAIGHT, 2027)
