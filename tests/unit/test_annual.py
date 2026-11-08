"""Annual overview: tax base, depreciation, receivables, payables, job profitability."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.assets import AssetBook, AssetDraft
from app.config import FirmaConfig
from app.contacts import KONTAKTY_SCHEMA
from app.invoices.service import DraftLine, InvoiceDraft, InvoiceService
from app.jobs import ZAKAZKY_SCHEMA
from app.journal import Account, EntryDraft, Journal, PaymentMethod
from app.received import Confirmation, ReceivedDocs
from app.storage import Storage
from app.tax.annual import annual_report, to_markdown

D = Decimal


@pytest.fixture
def firma() -> FirmaConfig:
    cfg = FirmaConfig()
    cfg.firma.nazev, cfg.firma.ico = "Jana Vzorová", "99999994"
    cfg.evidence.zacatek = "2027-01-01"
    cfg.evidence.pocatecni_hotovost = "1000,00"
    cfg.evidence.pocatecni_banka = "20000,00"
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
            "id": "Z2027-001",
            "kontakt_id": "K0001",
            "nazev": "Oprava střechy",
            "adresa_realizace": "",
            "stav": "rozpracováno",
            "datum_zalozeni": date(2027, 1, 2),
            "datum_dokonceni": None,
            "poznamka": "",
        }
    )
    return s


def test_annual_report(storage: Storage, firma: FirmaConfig) -> None:
    svc = InvoiceService(storage, firma)
    paid = svc.issue(
        InvoiceDraft(
            "K0001",
            date(2027, 3, 1),
            date(2027, 3, 15),
            [DraftLine("Práce", D("1"), "ks", D("50000"))],
            "Z2027-001",
        )
    )
    svc.mark_paid(paid["cislo"], date(2027, 3, 10), today=date(2027, 12, 31))
    open_inv = svc.issue(
        InvoiceDraft(
            "K0001",
            date(2027, 12, 20),
            date(2028, 1, 5),
            [DraftLine("Práce", D("1"), "ks", D("8000"))],
        )
    )
    docs = ReceivedDocs(storage, firma)
    docs.confirm(
        None,
        Confirmation(
            typ="faktura",
            dodavatel_ico="",
            dodavatel_nazev="Díly s.r.o.",
            cislo_dodavatele="1",
            datum_vystaveni=date(2027, 3, 2),
            datum_splatnosti=None,
            castka=D("12000"),
            vs="",
            ucet="",
            popis="Krytina",
            kategorie=15,
            zakazka_id="Z2027-001",
            zpusob_uhrady="převod",
            datum_uhrady=date(2027, 3, 3),
        ),
        today=date(2027, 12, 31),
    )
    docs.confirm(
        None,
        Confirmation(
            typ="faktura",
            dodavatel_ico="",
            dodavatel_nazev="Telefon a.s.",
            cislo_dodavatele="2",
            datum_vystaveni=date(2027, 12, 28),
            datum_splatnosti=date(2028, 1, 10),
            castka=D("500"),
            vs="",
            ucet="",
            popis="Telefon",
            kategorie=19,
            zakazka_id="",
            zpusob_uhrady="převod",
            datum_uhrady=None,
        ),
        today=date(2027, 12, 31),
    )
    Journal(storage, firma).add(
        EntryDraft(
            date(2027, 6, 1),
            Account.BANK,
            "výdaj",
            D("3000"),
            21,
            "Záloha OSVČ",
            PaymentMethod.TRANSFER,
        )
    )
    AssetBook(storage).add(AssetDraft("Dodávka", date(2027, 4, 1), D("300000"), 2, "rovnoměrný"))

    r = annual_report(storage, firma, 2027)
    assert r.income == D("50000.00")
    assert r.expenses == D("12000.00")
    assert r.depreciation == D("33000.00")  # 300 000 × 11 %
    assert r.tax_base == D("5000.00")  # 50 000 − 12 000 − 33 000
    assert r.not_affecting_expenses == D("3000.00")
    assert r.closing_bank == D("20000") + D("50000") - D("12000") - D("3000")
    assert [i["cislo"] for i in r.receivables] == [open_inv["cislo"]]
    assert [d["dodavatel_nazev"] for d in r.payables] == ["Telefon a.s."]
    (job,) = r.jobs
    assert (job["id"], job["prijmy"], job["naklady"], job["rozdil"]) == (
        "Z2027-001",
        D("50000.00"),
        D("12000.00"),
        D("38000.00"),
    )
    assert r.vz_social == D("2750.00")  # 55 % of 5 000
    assert r.vz_health == D("2500.00")  # 50 % of 5 000
    md = to_markdown(r, firma)
    assert "# Roční přehled 2027" in md
    assert "| Dílčí základ daně (§ 7) | 5 000,00 Kč |" in md
    assert "Dodávka" in md and open_inv["cislo"] in md


def test_loss_has_no_negative_assessment_base(storage: Storage, firma: FirmaConfig) -> None:
    Journal(storage, firma).add(
        EntryDraft(
            date(2027, 2, 1), Account.BANK, "výdaj", D("1000"), 19, "Nájem", PaymentMethod.TRANSFER
        )
    )
    r = annual_report(storage, firma, 2027)
    assert r.tax_base == D("-1000.00")
    assert r.vz_social == 0 and r.vz_health == 0
