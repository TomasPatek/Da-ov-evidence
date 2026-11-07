"""Invoice numbering, totals and SPAYD payment QR (tests written before the code)."""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

import pytest
from PIL import Image
from pyzbar.pyzbar import decode

from app.invoices.numbering import NumberingError, format_number, next_number, parse_number
from app.invoices.spayd import SpaydError, build_spayd, qr_png, qr_svg
from app.invoices.totals import invoice_total, line_total

# -- numbering ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("fmt", "year", "seq", "expected"),
    [("RRRRNNNN", 2026, 1, "20260001"), ("RRRRNNN", 2026, 42, "2026042")],
)
def test_format_and_parse_number(fmt: str, year: int, seq: int, expected: str) -> None:
    assert format_number(year, seq, fmt) == expected
    assert parse_number(expected, fmt) == (year, seq)


def test_format_number_overflow() -> None:
    with pytest.raises(NumberingError):
        format_number(2026, 1000, "RRRRNNN")


@pytest.mark.parametrize("bad", ["2026001", "20260000", "2026000A", "1999000x", ""])
def test_parse_number_rejects_garbage(bad: str) -> None:
    with pytest.raises(NumberingError):
        parse_number(bad, "RRRRNNNN")


def test_first_number_of_year_uses_start() -> None:
    assert next_number([], 2026, "RRRRNNNN", start=1) == "20260001"
    assert next_number([], 2026, "RRRRNNNN", start=57) == "20260057"


def test_next_number_has_no_gaps() -> None:
    existing = ["20260001", "20260002", "20260003"]
    assert next_number(existing, 2026, "RRRRNNNN", start=1) == "20260004"


def test_next_number_continues_after_highest_even_if_unsorted() -> None:
    assert next_number(["20260003", "20260001", "20260002"], 2026, "RRRRNNNN", 1) == "20260004"


def test_next_number_ignores_start_once_series_exists() -> None:
    assert next_number(["20260010"], 2026, "RRRRNNNN", start=50) == "20260011"


def test_new_year_starts_again() -> None:
    # Numbers of another year never influence the series.
    assert next_number(["20250099"], 2026, "RRRRNNNN", start=1) == "20260001"


def test_series_exhausted() -> None:
    with pytest.raises(NumberingError):
        next_number(["2026999"], 2026, "RRRRNNN", start=1)


# -- totals --------------------------------------------------------------------


def test_line_total_rounds_half_up_to_haler() -> None:
    assert line_total(Decimal("3"), Decimal("33.335")) == Decimal("100.01")
    assert line_total(Decimal("1.5"), Decimal("0.01")) == Decimal("0.02")
    assert line_total(Decimal("2.25"), Decimal("450")) == Decimal("1012.50")


def test_invoice_total_sums_rounded_lines() -> None:
    lines = [line_total(Decimal("1"), Decimal("0.005")), line_total(Decimal("1"), Decimal("0.005"))]
    # Each line is rounded first (0.01 + 0.01), not the raw sum (0.01).
    assert invoice_total(lines) == Decimal("0.02")


def test_totals_reject_floats() -> None:
    with pytest.raises(TypeError):
        line_total(1.5, Decimal("1"))  # type: ignore[arg-type]


def test_line_total_rejects_negative_quantity_times_price_overflow() -> None:
    # Negative lines (discounts) are allowed, the invoice total must stay positive.
    assert line_total(Decimal("-1"), Decimal("100")) == Decimal("-100.00")
    with pytest.raises(ValueError):
        invoice_total([Decimal("-100.00")])


# -- SPAYD ---------------------------------------------------------------------

IBAN = "CZ9501000000001234567899"


def test_spayd_basic_string() -> None:
    s = build_spayd(IBAN, Decimal("1234.50"), vs="20260001", message="Faktura 20260001")
    assert s == (
        "SPD*1.0*ACC:CZ9501000000001234567899*AM:1234.50*CC:CZK*X-VS:20260001*MSG:FAKTURA 20260001"
    )


def test_spayd_with_due_date_and_name() -> None:
    s = build_spayd(
        IBAN,
        Decimal("10"),
        vs="1",
        message="x",
        due=date(2026, 3, 15),
        recipient="Jana Vzorová",
    )
    assert "*DT:20260315" in s
    assert "*RN:JANA VZOROVA" in s
    assert "*AM:10.00*" in s


def test_spayd_escapes_asterisk_and_strips_diacritics() -> None:
    s = build_spayd(IBAN, Decimal("1"), vs="1", message="Oprava * střechy")
    assert s.endswith("*MSG:OPRAVA %2A STRECHY")


def test_spayd_truncates_message_to_60() -> None:
    s = build_spayd(IBAN, Decimal("1"), vs="1", message="A" * 80)
    assert s.endswith("*MSG:" + "A" * 60)


@pytest.mark.parametrize(
    ("iban", "amount", "vs"),
    [
        ("CZ9501000000001234567890", Decimal("1"), "1"),  # bad IBAN checksum
        (IBAN, Decimal("0"), "1"),
        (IBAN, Decimal("10000000"), "1"),  # AM max 10 chars
        (IBAN, Decimal("1"), "12345678901"),  # VS max 10 digits
        (IBAN, Decimal("1"), "12A"),
    ],
)
def test_spayd_rejects_invalid_input(iban: str, amount: Decimal, vs: str) -> None:
    with pytest.raises(SpaydError):
        build_spayd(iban, amount, vs=vs, message="")


def test_spayd_png_round_trip_through_qr_reader() -> None:
    payload = build_spayd(IBAN, Decimal("15200.00"), vs="20260001", message="Faktura 20260001")
    image = Image.open(io.BytesIO(qr_png(payload)))
    found = decode(image)
    assert [r.data.decode("ascii") for r in found] == [payload]


def test_spayd_svg_is_plain_svg() -> None:
    svg = qr_svg(build_spayd(IBAN, Decimal("1"), vs="1", message=""))
    assert svg.startswith("<svg") or svg.startswith("<?xml")
    assert "<script" not in svg
