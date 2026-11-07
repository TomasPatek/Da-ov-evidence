"""ET 328 columns and tax treatment (tests written before the code)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.tax.categories import (
    DHM_THRESHOLD,
    EXPENSE_COLUMNS,
    INCOME_COLUMNS,
    Direction,
    category,
    default_category,
    hints_for_expense,
)


def test_columns_match_et328() -> None:
    assert [c.column for c in INCOME_COLUMNS] == [9, 10, 11, 12, 13]
    assert [c.column for c in EXPENSE_COLUMNS] == [15, 16, 17, 18, 19, 20, 21, 22, 23]


@pytest.mark.parametrize(
    ("column", "affects"),
    [
        (9, True),
        (10, True),
        (11, False),
        (12, False),
        (13, False),
        (15, True),
        (16, True),
        (17, True),
        (18, True),
        (19, True),
        (20, False),
        (21, False),
        (22, False),
        (23, False),
    ],
)
def test_tax_base_effect(column: int, affects: bool) -> None:
    assert category(column).affects_tax_base is affects


def test_every_category_cites_the_income_tax_act() -> None:
    for c in (*INCOME_COLUMNS, *EXPENSE_COLUMNS):
        assert "586/1992" in c.legal_ref, c
        assert c.label


def test_direction_of_categories() -> None:
    assert all(c.direction is Direction.INCOME for c in INCOME_COLUMNS)
    assert all(c.direction is Direction.EXPENSE for c in EXPENSE_COLUMNS)


def test_unknown_column() -> None:
    with pytest.raises(KeyError):
        category(14)  # "výdaje celkem" is a total, not a category


def test_defaults() -> None:
    assert default_category(Direction.INCOME).column == 9
    assert default_category(Direction.EXPENSE).column == 15


def test_dhm_hint_above_threshold() -> None:
    assert Decimal("80000") == DHM_THRESHOLD
    assert hints_for_expense(15, Decimal("80000.00")) == []
    hints = hints_for_expense(19, Decimal("80000.01"))
    assert hints and "odpis" in hints[0]
    assert hints_for_expense(20, Decimal("100000")) == []
