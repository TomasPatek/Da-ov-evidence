"""Photo or scan of a cash document attached to a cash book entry."""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image

from app.config import FirmaConfig
from app.contacts import KONTAKTY_SCHEMA
from app.invoices.service import DraftLine, InvoiceDraft, InvoiceError, InvoiceService
from app.journal import Account, EntryDraft, Journal, JournalError, PaymentMethod
from app.storage import LockedYearError, Storage

D = Decimal


def jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, format="JPEG")
    return buf.getvalue()


PDF = b"%PDF-1.4\n%fake but recognised by its header\n"


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    storage = Storage(tmp_path / "data")
    storage.table(KONTAKTY_SCHEMA).insert(
        {
            "id": "K0001",
            "typ": "odběratel",
            "ico": "",
            "dic": "",
            "nazev": "Marie Hotová",
            "ulice": "",
            "mesto": "",
            "psc": "",
            "email": "",
            "telefon": "",
            "poznamka": "",
            "ares_aktualizovano": None,
        }
    )
    return storage


@pytest.fixture
def firma() -> FirmaConfig:
    cfg = FirmaConfig()
    cfg.evidence.zacatek = "2026-10-01"
    return cfg


@pytest.fixture
def journal(storage: Storage, firma: FirmaConfig) -> Journal:
    return Journal(storage, firma)


def cash_entry(journal: Journal) -> str:
    rec = journal.add(
        EntryDraft(
            date(2026, 10, 18), Account.CASH, "výdaj", D("120"), 16, "Drobný materiál",
            PaymentMethod.CASH,
        )
    )  # fmt: skip
    return str(rec["id"])


def test_attach_photo_to_entry(journal: Journal) -> None:
    entry_id = cash_entry(journal)
    rec = journal.attach(entry_id, jpeg())
    assert rec["priloha"] == f"pokladna/{entry_id}.jpg"
    path = journal.attachment_path(rec)
    assert path is not None and path.read_bytes()[:3] == b"\xff\xd8\xff"
    assert path.parent == journal.storage.data_dir / "2026" / "pokladna"


def test_new_attachment_replaces_old_one(journal: Journal) -> None:
    entry_id = cash_entry(journal)
    first = journal.attachment_path(journal.attach(entry_id, jpeg()))
    rec = journal.attach(entry_id, PDF)
    assert rec["priloha"] == f"pokladna/{entry_id}.pdf"
    assert first is not None and not first.exists()


def test_remove_attachment(journal: Journal) -> None:
    entry_id = cash_entry(journal)
    path = journal.attachment_path(journal.attach(entry_id, jpeg()))
    rec = journal.remove_attachment(entry_id)
    assert rec["priloha"] == "" and path is not None and not path.exists()


def test_deleting_entry_deletes_attachment(journal: Journal) -> None:
    entry_id = cash_entry(journal)
    path = journal.attachment_path(journal.attach(entry_id, jpeg()))
    journal.delete(entry_id)
    assert path is not None and not path.exists()


@pytest.mark.parametrize(
    ("data", "message"),
    [(b"", "prázdný"), (b"<html>hi</html>", "PDF nebo fotku"), (b"PK\x03\x04xx", "PDF nebo fotku")],
)
def test_only_pdf_and_photos(journal: Journal, data: bytes, message: str) -> None:
    entry_id = cash_entry(journal)
    with pytest.raises(JournalError, match=message):
        journal.attach(entry_id, data)
    assert not (journal.storage.data_dir / "2026" / "pokladna").exists()


def test_unknown_entry(journal: Journal) -> None:
    with pytest.raises(JournalError):
        journal.attach("D2026-0099", jpeg())
    with pytest.raises(JournalError):
        journal.attach("../../etc", jpeg())


def test_path_outside_folder_is_never_served(journal: Journal) -> None:
    entry_id = cash_entry(journal)
    rec = journal.attach(entry_id, jpeg())
    rec["priloha"] = "../../config/auth.json"
    assert journal.attachment_path(rec) is None


def test_locked_year_refuses_attachment(journal: Journal) -> None:
    entry_id = cash_entry(journal)
    journal.storage.set_locked(2026, True)
    with pytest.raises(LockedYearError):
        journal.attach(entry_id, jpeg())
    assert not (journal.storage.data_dir / "2026" / "pokladna").exists()


def _invoice(storage: Storage, firma: FirmaConfig) -> InvoiceService:
    service = InvoiceService(storage, firma)
    service.issue(
        InvoiceDraft(
            kontakt_id="K0001",
            datum_vystaveni=date(2026, 10, 15),
            datum_splatnosti=date(2026, 10, 29),
            lines=[DraftLine("Oprava sporáku", D("1"), "ks", D("1000"))],
        )
    )
    return service


def test_cash_payment_of_invoice_with_photo(storage: Storage, firma: FirmaConfig) -> None:
    service = _invoice(storage, firma)
    service.mark_paid(
        "20260001",
        date(2026, 10, 15),
        today=date(2026, 11, 8),
        method=PaymentMethod.CASH,
        attachment=jpeg(),
    )
    (row,) = Journal(storage, firma).for_document("20260001")
    assert row["cislo_dokladu"] == "PPD1/26"
    assert row["priloha"] == f"pokladna/{row['id']}.jpg"


def test_bad_photo_does_not_record_payment(storage: Storage, firma: FirmaConfig) -> None:
    service = _invoice(storage, firma)
    with pytest.raises(InvoiceError, match="PDF nebo fotku"):
        service.mark_paid(
            "20260001",
            date(2026, 10, 15),
            today=date(2026, 11, 8),
            method=PaymentMethod.CASH,
            attachment=b"not a picture",
        )
    assert Journal(storage, firma).for_document("20260001") == []
    assert (service.get("20260001") or {})["stav"] == "vystavena"


def test_photo_needs_a_cash_book_entry(storage: Storage, firma: FirmaConfig) -> None:
    service = _invoice(storage, firma)
    with pytest.raises(InvoiceError, match="před začátkem evidence"):
        service.mark_paid(
            "20260001",
            date(2026, 9, 30),
            today=date(2026, 11, 8),
            method=PaymentMethod.CASH,
            attachment=jpeg(),
        )


def test_older_cash_book_without_column_still_works(journal: Journal) -> None:
    entry_id = cash_entry(journal)
    path = journal.storage.data_dir / "2026" / "denik.csv"
    header, row = path.read_text("utf-8-sig").splitlines()[:2]
    # Version 1.0.0 files have no "priloha" column.
    path.write_text(
        "﻿" + header.rsplit(";", 1)[0] + "\r\n" + row.rsplit(";", 1)[0] + "\r\n",
        encoding="utf-8",
    )
    assert journal.get(entry_id)["priloha"] == ""
    assert journal.attach(entry_id, jpeg())["priloha"] == f"pokladna/{entry_id}.jpg"
    assert path.read_text("utf-8-sig").splitlines()[0].endswith(";priloha")
