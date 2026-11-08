"""Locked year: its records cannot change, late payments of its invoices still can."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import FirmaConfig
from app.contacts import KONTAKTY_SCHEMA
from app.invoices.service import DraftLine, InvoiceDraft, InvoiceService
from app.journal import Account, EntryDraft, Journal, PaymentMethod
from app.storage import LockedYearError, Storage

D = Decimal


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Storage, FirmaConfig]:
    storage = Storage(tmp_path / "data")
    storage.table(KONTAKTY_SCHEMA).insert(
        {
            "id": "K0001",
            "typ": "odběratel",
            "ico": "",
            "dic": "",
            "nazev": "Petr",
            "ulice": "",
            "mesto": "",
            "psc": "",
            "email": "",
            "telefon": "",
            "poznamka": "",
            "ares_aktualizovano": None,
        }
    )
    firma = FirmaConfig()
    firma.evidence.zacatek = "2026-01-01"
    return storage, firma


def entry(day: date) -> EntryDraft:
    return EntryDraft(day, Account.BANK, "výdaj", D("100"), 19, "Nájem", PaymentMethod.TRANSFER)


def test_locked_year_refuses_changes(setup: tuple[Storage, FirmaConfig]) -> None:
    storage, firma = setup
    journal = Journal(storage, firma)
    row = journal.add(entry(date(2026, 5, 1)))
    storage.set_locked(2026, True)
    assert storage.locked_years() == [2026]
    with pytest.raises(LockedYearError, match="Rok 2026 je uzamčený"):
        journal.add(entry(date(2026, 6, 1)))
    with pytest.raises(LockedYearError):
        journal.delete(row["id"])
    journal.add(entry(date(2027, 1, 5)))  # the next year is open
    storage.set_locked(2026, False)
    journal.delete(row["id"])
    changes = [e for e in storage.audit.entries() if e["zaznam_id"] == "rok"]
    assert [(e["stara_hodnota"], e["nova_hodnota"]) for e in changes] == [
        ("ne", "ano"),
        ("ano", "ne"),
    ]


def test_invoice_of_locked_year_can_be_paid_later(setup: tuple[Storage, FirmaConfig]) -> None:
    storage, firma = setup
    svc = InvoiceService(storage, firma)
    inv = svc.issue(
        InvoiceDraft(
            "K0001",
            date(2026, 12, 20),
            date(2027, 1, 5),
            [DraftLine("Práce", D("1"), "ks", D("1000"))],
        )
    )
    storage.set_locked(2026, True)
    with pytest.raises(LockedYearError):
        svc.issue(
            InvoiceDraft(
                "K0001",
                date(2026, 12, 21),
                date(2027, 1, 5),
                [DraftLine("Práce", D("1"), "ks", D("1"))],
            )
        )
    with pytest.raises(LockedYearError):
        svc.cancel(inv["cislo"], "pozdě")
    paid = svc.mark_paid(inv["cislo"], date(2027, 1, 4), today=date(2027, 1, 10))
    assert paid["stav"] == "uhrazena"
    assert Journal(storage, firma).for_document(inv["cislo"])[0]["datum_uhrady"] == date(2027, 1, 4)
