"""Cash book (peněžní deník) on real CSV files, checked against the ET 328 sample."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import FirmaConfig
from app.journal import (
    Account,
    EntryDraft,
    Journal,
    JournalError,
    PaymentMethod,
)
from app.storage import Storage

D = Decimal


@pytest.fixture
def firma() -> FirmaConfig:
    cfg = FirmaConfig()
    cfg.evidence.zacatek = "2027-01-01"
    cfg.evidence.pocatecni_hotovost = "100,00"
    cfg.evidence.pocatecni_banka = "500,00"
    return cfg


@pytest.fixture
def journal(tmp_path: Path, firma: FirmaConfig) -> Journal:
    return Journal(Storage(tmp_path / "data"), firma)


def entry(
    day: date,
    account: Account,
    direction: str,
    amount: str,
    column: int,
    text: str = "",
    **kw: object,
) -> EntryDraft:
    method = kw.pop(
        "method", PaymentMethod.CASH if account is Account.CASH else PaymentMethod.TRANSFER
    )
    return EntryDraft(
        datum=day,
        ucet=account,
        smer=direction,
        castka=D(amount),
        kategorie=column,
        popis=text or f"sloupec {column}",
        zpusob_uhrady=method,
        **kw,  # type: ignore[arg-type]
    )


def test_et328_sample_month(journal: Journal) -> None:
    """The worked example printed in the ET 328 booklet (January, rows 2-19)."""
    j = 2027
    C, B = Account.CASH, Account.BANK
    rows = [
        entry(date(j, 1, 1), C, "příjem", "17", 9, "Tržba v hotovosti"),
        entry(date(j, 1, 3), C, "výdaj", "50", 15, "Nákup materiálu hotově"),
        entry(date(j, 1, 5), B, "výdaj", "22", 16, "Úhrada faktury za zboží"),
        entry(date(j, 1, 7), B, "výdaj", "61", 20, "Počítač (DHM)"),
        entry(date(j, 1, 10), C, "příjem", "15", 12, "Vklad podnikatele"),
        entry(date(j, 1, 16), C, "výdaj", "21", 17, "Výplata mezd"),
        entry(date(j, 1, 16), B, "výdaj", "3", 18, "Zdravotní pojištění zaměstnanců"),
        entry(date(j, 1, 16), B, "výdaj", "7", 18, "Sociální pojištění zaměstnanců"),
        entry(date(j, 1, 16), B, "výdaj", "4", 17, "Záloha na daň zaměstnanců"),
        entry(date(j, 1, 17), C, "výdaj", "2", 23, "Pohoštění"),
        entry(date(j, 1, 20), C, "výdaj", "1", 19, "Cestovné"),
        entry(date(j, 1, 25), B, "příjem", "105", 9, "Úhrada odběratelské faktury"),
        entry(date(j, 1, 28), C, "výdaj", "9", 23, "Osobní spotřeba"),
        entry(date(j, 1, 31), B, "příjem", "5", 13, "Úroky z BÚ"),
        entry(date(j, 1, 31), B, "výdaj", "2", 21, "Sociální pojištění OSVČ"),
        entry(date(j, 1, 31), B, "výdaj", "1", 21, "Zdravotní pojištění OSVČ"),
    ]
    for r in rows:
        journal.add(r)
    journal.transfer(date(j, 1, 22), Account.BANK, Account.CASH, D("12"), "Výběr do pokladny")

    report = journal.et_report(j)
    t = report.totals
    # Column totals from the "převádí se" row of the sample (without the opening row).
    assert t[1] == D("44")  # sample: 144 incl. 100 opening
    assert t[2] == D("83")
    assert t[4] == D("110")  # sample: 610 incl. 500 opening
    assert t[5] == D("112")
    assert t[6] == D("12") and t[7] == D("12")
    assert t[8] == D("142")
    assert t[9] == D("122") and t[12] == D("15") and t[13] == D("5")
    assert t[14] == D("183")
    assert (t[15], t[16], t[17], t[18], t[19]) == (D("50"), D("22"), D("25"), D("10"), D("1"))
    assert (t[20], t[21], t[22], t[23]) == (D("61"), D("3"), D("0"), D("11"))
    assert report.checks_ok
    assert report.opening_cash == D("100") and report.opening_bank == D("500")
    # Check from the booklet: 1 - 2 + 4 - 5 + 6 - 7 - 8 + 14 = opening balances (1 + 4).
    assert report.closing_cash == D("61")
    assert report.closing_bank == D("498")
    assert report.rows[-1].cash_balance == D("61")


def test_cash_and_document_numbers(journal: Journal) -> None:
    a = journal.add(entry(date(2027, 1, 2), Account.CASH, "příjem", "10", 9))
    b = journal.add(entry(date(2027, 1, 3), Account.CASH, "výdaj", "5", 15))
    c = journal.add(entry(date(2027, 1, 4), Account.CASH, "příjem", "1", 9))
    d = journal.add(entry(date(2027, 1, 5), Account.BANK, "výdaj", "1", 19))
    e = journal.add(entry(date(2027, 1, 5), Account.BANK, "výdaj", "1", 15, doklad_id="PD2027-004"))
    assert [a["cislo_dokladu"], b["cislo_dokladu"], c["cislo_dokladu"]] == [
        "PPD1/27",
        "VPD1/27",
        "PPD2/27",
    ]
    assert d["cislo_dokladu"] == "B1"
    assert e["cislo_dokladu"] == "PD2027-004"
    assert a["id"] == "D2027-0001" and e["id"] == "D2027-0005"
    assert a["danove_uznatelny"] is True
    assert (
        journal.add(entry(date(2027, 2, 1), Account.BANK, "výdaj", "1", 21))["danove_uznatelny"]
        is False
    )


@pytest.mark.parametrize(
    ("direction", "column"), [("příjem", 15), ("výdaj", 9), ("příjem", 6), ("výdaj", 99)]
)
def test_category_must_match_direction(journal: Journal, direction: str, column: int) -> None:
    with pytest.raises(JournalError, match="Kategorie"):
        journal.add(entry(date(2027, 1, 2), Account.BANK, direction, "1", column))


def test_amount_must_be_positive(journal: Journal) -> None:
    with pytest.raises(JournalError, match="kladná"):
        journal.add(entry(date(2027, 1, 2), Account.BANK, "výdaj", "0", 15))


def test_cash_requires_cash_method(journal: Journal) -> None:
    with pytest.raises(JournalError, match="hotovost"):
        journal.add(
            entry(date(2027, 1, 2), Account.CASH, "výdaj", "1", 15, method=PaymentMethod.CARD)
        )
    with pytest.raises(JournalError, match="hotovost"):
        journal.add(
            entry(date(2027, 1, 2), Account.BANK, "výdaj", "1", 15, method=PaymentMethod.CASH)
        )


def test_entries_before_start_are_refused(journal: Journal) -> None:
    with pytest.raises(JournalError, match=r"1\. 1\. 2027"):
        journal.add(entry(date(2026, 12, 31), Account.BANK, "výdaj", "1", 15))


def test_not_set_up(tmp_path: Path) -> None:
    j = Journal(Storage(tmp_path / "data"), FirmaConfig())
    assert not j.ready
    with pytest.raises(JournalError, match="začátek"):
        j.add(entry(date(2027, 1, 2), Account.BANK, "výdaj", "1", 15))


def test_negative_cash_is_reported(journal: Journal) -> None:
    journal.add(entry(date(2027, 1, 2), Account.CASH, "výdaj", "150", 15))
    report = journal.et_report(2027)
    assert report.closing_cash == D("-50")
    assert any("záporný" in w for w in report.warnings)


def test_next_year_opens_with_previous_closing(journal: Journal) -> None:
    journal.add(entry(date(2027, 3, 1), Account.BANK, "příjem", "1000", 9))
    journal.add(entry(date(2027, 3, 2), Account.CASH, "výdaj", "40", 19))
    nxt = journal.et_report(2028)
    assert nxt.opening_bank == D("1500.00")
    assert nxt.opening_cash == D("60.00")


def test_months_and_order(journal: Journal) -> None:
    journal.add(entry(date(2027, 2, 10), Account.BANK, "příjem", "5", 9))
    journal.add(entry(date(2027, 1, 20), Account.BANK, "příjem", "7", 9))
    report = journal.et_report(2027)
    assert [r.entry["datum_uhrady"].month for r in report.rows] == [1, 2]
    assert report.month_totals[1][8] == D("7")
    assert report.month_totals[2][8] == D("5")
    assert set(report.month_totals) == {1, 2}


def test_transfer_creates_two_rows_with_transit_columns(journal: Journal) -> None:
    out, inn = journal.transfer(
        date(2027, 1, 5), Account.CASH, Account.BANK, D("30"), "Vklad na účet"
    )
    assert (out["ucet"], out["smer"], out["kategorie"]) == ("hotovost", "výdaj", 6)
    assert (inn["ucet"], inn["smer"], inn["kategorie"]) == ("banka", "příjem", 7)
    assert out["cislo_dokladu"] == "VPD1/27"
    report = journal.et_report(2027)
    assert report.totals[8] == 0 and report.totals[14] == 0
    with pytest.raises(JournalError):
        journal.transfer(date(2027, 1, 5), Account.CASH, Account.CASH, D("1"), "x")


def test_delete_and_entries_for_document(journal: Journal) -> None:
    row = journal.add(
        entry(date(2027, 1, 2), Account.BANK, "příjem", "10", 9, doklad_id="20270001")
    )
    assert [r["id"] for r in journal.for_document("20270001")] == [row["id"]]
    journal.remove_for_document("20270001")
    assert journal.entries(2027) == []


def test_tax_summary(journal: Journal) -> None:
    journal.add(entry(date(2027, 1, 2), Account.BANK, "příjem", "1000", 9))
    journal.add(entry(date(2027, 1, 3), Account.BANK, "příjem", "500", 12))
    journal.add(entry(date(2027, 1, 4), Account.BANK, "výdaj", "300", 15))
    journal.add(entry(date(2027, 1, 5), Account.BANK, "výdaj", "200", 21))
    s = journal.et_report(2027)
    assert s.taxable_income == D("1000")
    assert s.deductible_expenses == D("300")
    assert s.profit == D("700")


def test_cash_numbers_restart_each_year(journal: Journal) -> None:
    journal.add(entry(date(2027, 12, 30), Account.CASH, "příjem", "10", 9))
    journal.add(entry(date(2027, 12, 31), Account.CASH, "výdaj", "1", 19))
    a = journal.add(entry(date(2028, 1, 2), Account.CASH, "příjem", "10", 9))
    b = journal.add(entry(date(2028, 1, 3), Account.CASH, "výdaj", "1", 19))
    assert (a["cislo_dokladu"], b["cislo_dokladu"]) == ("PPD1/28", "VPD1/28")


def test_bank_rows_use_transaction_code(journal: Journal) -> None:
    coded = journal.add(
        entry(
            date(2027, 1, 5),
            Account.BANK,
            "výdaj",
            "1",
            15,
            doklad_id="PD2027-001",
            kod_transakce=" 123456789 ",
        )
    )
    assert coded["cislo_dokladu"] == "123456789"
    assert coded["doklad_id"] == "PD2027-001"
    # Without a code the document number (or B1) is used as before.
    assert (
        journal.add(entry(date(2027, 1, 6), Account.BANK, "výdaj", "1", 15))["cislo_dokladu"]
        == "B1"
    )
    # Cash vouchers are always numbered by the app.
    cash = journal.add(entry(date(2027, 1, 7), Account.CASH, "výdaj", "1", 15, kod_transakce="X1"))
    assert cash["cislo_dokladu"] == "VPD1/27"


def test_invalid_transaction_code(journal: Journal) -> None:
    with pytest.raises(JournalError, match="Kód transakce"):
        journal.add(entry(date(2027, 1, 5), Account.BANK, "výdaj", "1", 15, kod_transakce="a b;c"))


def test_transfer_bank_side_gets_code(journal: Journal) -> None:
    out, inn = journal.transfer(
        date(2027, 1, 5), Account.BANK, Account.CASH, D("30"), "Výběr", kod_transakce="987654"
    )
    assert (out["cislo_dokladu"], inn["cislo_dokladu"]) == ("987654", "PPD1/27")
