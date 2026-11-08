"""Bank movements: import, duplicates, automatic and suggested matching, booking."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.banks.book import BankBook, BankError, MatchState
from app.banks.model import BankMovement, Direction, Source
from app.config import FirmaConfig
from app.contacts import KONTAKTY_SCHEMA
from app.invoices.service import DraftLine, InvoiceDraft, InvoiceService
from app.jobs import ZAKAZKY_SCHEMA
from app.journal import Journal, PaymentMethod
from app.received import Confirmation, ReceivedDocs
from app.storage import Storage

D = Decimal
OWN = "1000000005/3030"


@pytest.fixture
def firma() -> FirmaConfig:
    cfg = FirmaConfig()
    cfg.firma.ico = "99999994"
    cfg.banka.ucet = OWN
    cfg.evidence.zacatek = "2026-01-01"
    cfg.evidence.pocatecni_banka = "10000,00"
    return cfg


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    s = Storage(tmp_path / "data")
    s.table(KONTAKTY_SCHEMA).insert(
        {
            "id": "K0001",
            "typ": "odběratel",
            "ico": "",
            "dic": "",
            "nazev": "Petr Zákazník",
            "ulice": "",
            "mesto": "",
            "psc": "",
            "email": "",
            "telefon": "",
            "poznamka": "",
            "ares_aktualizovano": None,
        }
    )
    s.table(ZAKAZKY_SCHEMA).insert(
        {
            "id": "Z2026-001",
            "kontakt_id": "K0001",
            "nazev": "Oprava",
            "adresa_realizace": "",
            "stav": "rozpracováno",
            "datum_zalozeni": date(2026, 1, 2),
            "datum_dokonceni": None,
            "poznamka": "",
        }
    )
    return s


@pytest.fixture
def book(storage: Storage, firma: FirmaConfig) -> BankBook:
    return BankBook(storage, firma)


def invoice(storage: Storage, firma: FirmaConfig, amount: str = "4100", job: str = "") -> str:
    svc = InvoiceService(storage, firma)
    draft = InvoiceDraft(
        "K0001",
        date(2026, 10, 1),
        date(2026, 10, 15),
        [DraftLine("Práce", D("1"), "ks", D(amount))],
        job,
    )
    return str(svc.issue(draft)["cislo"])


def movement(**kw: object) -> BankMovement:
    base = BankMovement(
        datum=date(2026, 10, 10),
        smer=Direction.IN,
        castka=D("4100.00"),
        ucet=OWN,
        kod_transakce="900000000004",
        protiucet="4000000009/2010",
        vs="20260001",
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def test_import_and_duplicate_notification(book: BankBook) -> None:
    rec, created = book.import_movement(movement())
    assert created and rec["id"] == "BP2026-0001" and rec["stav"] == "nespárováno"
    again, created = book.import_movement(movement())
    assert not created and again["id"] == rec["id"]
    assert len(book.all()) == 1


def test_statement_completes_notification(book: BankBook) -> None:
    book.import_movement(movement(zprava="", ks=""))
    merged, created = book.import_movement(
        movement(zdroj=Source.STATEMENT, ks="0308", zprava="Faktura")
    )
    assert not created
    assert merged["zdroj"] == "notifikace, výpis"
    assert (merged["ks"], merged["zprava"]) == ("0308", "Faktura")


def test_other_account_is_refused(book: BankBook) -> None:
    with pytest.raises(BankError, match="jinému účtu"):
        book.import_movement(movement(ucet="2000000018/3030"))


def test_vs_and_amount_match_automatically(
    book: BankBook, storage: Storage, firma: FirmaConfig
) -> None:
    cislo = invoice(storage, firma, job="Z2026-001")
    rec, _ = book.import_movement(movement(vs=cislo))
    done = book.auto_match(rec)
    assert done["stav"] == "spárováno" and done["parovani"] == cislo
    inv = InvoiceService(storage, firma).get(cislo)
    assert (
        inv is not None and inv["stav"] == "uhrazena" and inv["datum_uhrady"] == date(2026, 10, 10)
    )
    (row,) = Journal(storage, firma).for_document(cislo)
    assert row["cislo_dokladu"] == "900000000004" and row["castka"] == D("4100.00")
    assert done["denik_id"] == row["id"]
    assert storage.table(ZAKAZKY_SCHEMA).get("Z2026-001")["stav"] == "uhrazeno"  # type: ignore[index]


def test_partial_payment_is_only_suggested(
    book: BankBook, storage: Storage, firma: FirmaConfig
) -> None:
    cislo = invoice(storage, firma)
    rec, _ = book.import_movement(movement(vs=cislo, castka=D("1000.00")))
    assert book.auto_match(rec)["stav"] == "nespárováno"
    (cand,) = book.candidates(rec)
    assert cand.target == cislo and not cand.exact and "částečná úhrada" in cand.note
    book.match(rec["id"], "faktura", cislo)
    svc = InvoiceService(storage, firma)
    assert svc.get(cislo)["stav"] == "vystavena"  # type: ignore[index]
    assert svc.remaining(svc.get(cislo)) == D("3100.00")  # type: ignore[arg-type]
    # The rest arrives later and matches automatically (VS and remaining amount).
    rest, _ = book.import_movement(
        movement(vs=cislo, castka=D("3100.00"), kod_transakce="900000000005")
    )
    assert book.auto_match(rest)["stav"] == "spárováno"
    assert svc.get(cislo)["stav"] == "uhrazena"  # type: ignore[index]


def test_overpayment_is_suggested(book: BankBook, storage: Storage, firma: FirmaConfig) -> None:
    cislo = invoice(storage, firma)
    rec, _ = book.import_movement(movement(vs=cislo, castka=D("4200.00")))
    (cand,) = book.candidates(rec)
    assert "přeplatek 100.00" in cand.note
    book.match(rec["id"], "faktura", cislo)
    assert Journal(storage, firma).for_document(cislo)[0]["castka"] == D("4200.00")


def test_amount_only_is_suggestion(book: BankBook, storage: Storage, firma: FirmaConfig) -> None:
    invoice(storage, firma)
    rec, _ = book.import_movement(movement(vs=""))
    (cand,) = book.candidates(rec)
    assert not cand.exact and cand.note == "sedí jen částka"
    assert book.auto_match(rec)["stav"] == "nespárováno"


def test_two_exact_candidates_are_not_matched(
    book: BankBook, storage: Storage, firma: FirmaConfig
) -> None:
    a = invoice(storage, firma)
    invoice(storage, firma)
    rec, _ = book.import_movement(movement(vs=a.lstrip("0")))
    # Only one invoice has this VS, so it is matched; amount-only one stays a suggestion.
    assert book.auto_match(rec)["parovani"] == a


def confirm_doc(storage: Storage, firma: FirmaConfig, **kw: object) -> str:
    docs = ReceivedDocs(storage, firma)
    base: dict[str, object] = dict(
        typ="faktura",
        dodavatel_ico="",
        dodavatel_nazev="Díly Vzor s.r.o.",
        cislo_dodavatele="1",
        datum_vystaveni=date(2026, 9, 20),
        datum_splatnosti=None,
        castka=D("1815.00"),
        vs="2027000123",
        ucet="3000000004/0800",
        popis="Díly",
        kategorie=15,
        zakazka_id="",
        zpusob_uhrady="převod",
        datum_uhrady=None,
    )
    base.update(kw)
    return str(docs.confirm(None, Confirmation(**base), today=date(2026, 12, 31))["id"])  # type: ignore[arg-type]


def test_outgoing_payment_pays_document(
    book: BankBook, storage: Storage, firma: FirmaConfig
) -> None:
    doc_id = confirm_doc(storage, firma)
    rec, _ = book.import_movement(
        movement(
            smer=Direction.OUT,
            castka=D("1815.00"),
            vs="2027000123",
            protiucet="3000000004/0800",
            kod_transakce="900000000001",
        )
    )
    done = book.auto_match(rec)
    assert done["parovani"] == doc_id
    (row,) = Journal(storage, firma).for_document(doc_id)
    assert (row["smer"], row["cislo_dokladu"], row["kategorie"]) == ("výdaj", "900000000001", 15)
    assert ReceivedDocs(storage, firma).get(doc_id)["stav"] == "uhrazen"  # type: ignore[index]
    book.unmatch(done["id"])
    assert ReceivedDocs(storage, firma).get(doc_id)["stav"] == "potvrzen"  # type: ignore[index]
    assert Journal(storage, firma).for_document(doc_id) == []


def test_account_and_amount_without_vs_is_suggestion(
    book: BankBook, storage: Storage, firma: FirmaConfig
) -> None:
    doc_id = confirm_doc(storage, firma, vs="")
    rec, _ = book.import_movement(
        movement(smer=Direction.OUT, castka=D("1815.00"), vs="", protiucet="3000000004/0800")
    )
    (cand,) = book.candidates(rec)
    assert cand.target == doc_id and not cand.exact and cand.note == "sedí účet a částka"


def test_card_payment_attaches_code_to_paid_document(
    book: BankBook, storage: Storage, firma: FirmaConfig
) -> None:
    doc_id = confirm_doc(
        storage,
        firma,
        castka=D("249.00"),
        vs="",
        zpusob_uhrady="karta",
        datum_uhrady=date(2026, 10, 10),
    )
    journal = Journal(storage, firma)
    assert journal.for_document(doc_id)[0]["cislo_dokladu"] == doc_id
    rec, _ = book.import_movement(
        movement(
            smer=Direction.OUT,
            castka=D("249.00"),
            vs="",
            protiucet="",
            popis="Platba Cvakem",
            datum=date(2026, 10, 12),
            kod_transakce="900000000002",
        )
    )
    (cand,) = book.candidates(rec)
    assert cand.attach_code
    book.match(rec["id"], "doklad", doc_id)
    (row,) = journal.for_document(doc_id)
    assert row["cislo_dokladu"] == "900000000002"
    book.unmatch(rec["id"])
    assert journal.for_document(doc_id)[0]["cislo_dokladu"] == doc_id
    assert ReceivedDocs(storage, firma).get(doc_id)["stav"] == "uhrazen"  # type: ignore[index]


def test_book_other_and_transfer(book: BankBook, storage: Storage, firma: FirmaConfig) -> None:
    fee, _ = book.import_movement(
        movement(smer=Direction.OUT, castka=D("2900.00"), vs="", kod_transakce="1")
    )
    book.book_other(fee["id"], 21, "Záloha na sociální pojištění")
    deposit, _ = book.import_movement(
        movement(
            castka=D("3000.00"), vs="", kod_transakce="2", popis="Vklad na aliančním bankomatu"
        )
    )
    book.book_transfer(deposit["id"])
    rows = Journal(storage, firma).entries(2026)
    assert [(r["cislo_dokladu"], r["kategorie"], r["ucet"]) for r in rows] == [
        ("1", 21, "banka"),
        ("VPD1/26", 6, "hotovost"),
        ("2", 7, "banka"),
    ]
    book.unmatch(deposit["id"])
    assert [r["cislo_dokladu"] for r in Journal(storage, firma).entries(2026)] == ["1"]


def test_ignore_requires_reason_and_processed_cannot_be_matched_again(book: BankBook) -> None:
    rec, _ = book.import_movement(movement(vs=""))
    with pytest.raises(BankError, match="důvod"):
        book.ignore(rec["id"], " ")
    book.ignore(rec["id"], "Soukromá platba omylem z podnikatelského účtu, vrácena")
    with pytest.raises(BankError, match="zpracovaný"):
        book.book_other(rec["id"], 23, "x")
    assert book.open_movements() == []
    assert book.unmatch(rec["id"])["stav"] == MatchState.OPEN


def test_wrong_direction_is_refused(book: BankBook, storage: Storage, firma: FirmaConfig) -> None:
    cislo = invoice(storage, firma)
    rec, _ = book.import_movement(movement(smer=Direction.OUT, vs=cislo))
    with pytest.raises(BankError, match="příchozí"):
        book.match(rec["id"], "faktura", cislo)


def test_cash_invoice_method_untouched(storage: Storage, firma: FirmaConfig) -> None:
    # Manual payments keep working next to bank matching.
    cislo = invoice(storage, firma)
    InvoiceService(storage, firma).mark_paid(cislo, date(2026, 10, 2), method=PaymentMethod.CASH)
    assert Journal(storage, firma).for_document(cislo)[0]["cislo_dokladu"] == "PPD1/26"
