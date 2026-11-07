from decimal import Decimal

import pytest

from app.money import (
    format_csv_amount,
    format_csv_decimal,
    format_display_amount,
    parse_csv_amount,
    parse_csv_decimal,
    parse_user_amount,
    round_money,
    sum_money,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.005", "1.01"),  # half up, not banker's rounding
        ("1.004", "1.00"),
        ("2.675", "2.68"),
        ("-1.005", "-1.01"),  # symmetric for negatives
        ("0", "0.00"),
        ("1234.5", "1234.50"),
    ],
)
def test_round_money(value: str, expected: str) -> None:
    assert round_money(Decimal(value)) == Decimal(expected)
    assert str(round_money(Decimal(value))) == expected


def test_round_money_rejects_float() -> None:
    with pytest.raises(TypeError):
        round_money(1.5)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1234,50", Decimal("1234.50")),
        ("0,01", Decimal("0.01")),
        ("-12,00", Decimal("-12.00")),
        ("15", Decimal("15.00")),
        ("1,5", Decimal("1.50")),
    ],
)
def test_parse_csv_amount(text: str, expected: Decimal) -> None:
    assert parse_csv_amount(text) == expected


@pytest.mark.parametrize(
    "text", ["1 234,50", "1.234,50", "1234.50", "abc", "", "1,234", "NaN", "Infinity"]
)
def test_parse_csv_amount_rejects_invalid(text: str) -> None:
    with pytest.raises(ValueError):
        parse_csv_amount(text)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1234.5"), "1234,50"),
        (Decimal("0"), "0,00"),
        (Decimal("-0.5"), "-0,50"),
        (Decimal("1000000"), "1000000,00"),
        (Decimal("1E+3"), "1000,00"),
    ],
)
def test_format_csv_amount(value: Decimal, expected: str) -> None:
    assert format_csv_amount(value) == expected


@pytest.mark.parametrize("text", ["0,00", "1234,50", "-99,99", "1000000,01"])
def test_csv_amount_round_trip(text: str) -> None:
    assert format_csv_amount(parse_csv_amount(text)) == text


def test_format_csv_amount_rejects_unrounded() -> None:
    # Rounding must happen explicitly via round_money, never silently on output.
    with pytest.raises(ValueError):
        format_csv_amount(Decimal("1.005"))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 234,50", Decimal("1234.50")),
        ("1 234,5", Decimal("1234.50")),
        ("1234.50", Decimal("1234.50")),
        (" 12 ", Decimal("12.00")),
        ("12,345", Decimal("12.35")),
    ],
)
def test_parse_user_amount(text: str, expected: Decimal) -> None:
    assert parse_user_amount(text) == expected


@pytest.mark.parametrize("text", ["", "1,2,3", "12a", "1.234,50"])
def test_parse_user_amount_rejects_invalid(text: str) -> None:
    with pytest.raises(ValueError):
        parse_user_amount(text)


def test_format_display_amount() -> None:
    assert format_display_amount(Decimal("1234567.5")) == "1 234 567,50 Kč"
    assert format_display_amount(Decimal("-5"), currency="EUR") == "-5,00 EUR"


def test_sum_money_rounds_each_line_then_sums() -> None:
    # Each line is rounded to haléře before summing (as printed on the invoice).
    assert sum_money([Decimal("0.005"), Decimal("0.005")]) == Decimal("0.02")
    assert sum_money([]) == Decimal("0.00")


@pytest.mark.parametrize(
    ("text", "expected"),
    [("1,5", Decimal("1.5")), ("2", Decimal("2")), ("0,125", Decimal("0.125"))],
)
def test_csv_decimal_round_trip(text: str, expected: Decimal) -> None:
    assert parse_csv_decimal(text) == expected
    assert format_csv_decimal(expected) == text


def test_format_csv_decimal_strips_trailing_zeros() -> None:
    assert format_csv_decimal(Decimal("1.500")) == "1,5"
    assert format_csv_decimal(Decimal("10")) == "10"
    assert format_csv_decimal(Decimal("1E+1")) == "10"
