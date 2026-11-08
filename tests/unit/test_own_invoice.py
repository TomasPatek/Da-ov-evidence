"""Invoices issued in Air Bank: recognised on upload and taken over into issued invoices."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import FirmaConfig
from app.contacts import KONTAKTY_SCHEMA
from app.ingest.own_invoice import Customer
from app.invoices.service import DraftLine, InvoiceDraft, InvoiceError, InvoiceService
from app.received import ReceivedDocs, ReceivedError
from app.storage import Storage

FIXTURE = Path(__file__).parents[1] / "fixtures" / "doklady" / "vydana-airbank.pdf"
D = Decimal


@pytest.fixture
def firma() -> FirmaConfig:
    cfg = FirmaConfig()
    cfg.firma.ico = "99999994"
    cfg.banka.ucet = "1000000005/3030"
    cfg.banka.iban = "CZ0330300000001000000005"
    cfg.evidence.zacatek = "2026-01-01"
    return cfg


@pytest.fixture
def docs(tmp_path: Path, firma: FirmaConfig) -> ReceivedDocs:
    return ReceivedDocs(Storage(tmp_path / "data"), firma)


def draft(**kw: object) -> InvoiceDraft:
    base: dict[str, object] = dict(
        kontakt_id="",
        datum_vystaveni=date(2026, 11, 5),
        datum_splatnosti=date(2026, 11, 19),
        lines=[DraftLine("Oprava pračky", D("1"), "ks", D("1250"))],
    )
    base.update(kw)
    return InvoiceDraft(**base)  # type: ignore[arg-type]


def test_upload_recognises_own_invoice(docs: ReceivedDocs) -> None:
    rec = docs.upload(FIXTURE.read_bytes(), today=date(2026, 11, 8))
    assert rec["typ"] == "vydaná faktura"
    assert rec["dodavatel_nazev"] == "Petr Zákazník"
    assert rec["cislo_dodavatele"] == "20260042"
    own = docs.own_invoice(rec)
    assert own is not None and own.castka == D("1250.00") and own.customer.mesto == "Vzorov"


def test_take_over_creates_invoice_and_continues_series(
    docs: ReceivedDocs, firma: FirmaConfig
) -> None:
    rec = docs.upload(FIXTURE.read_bytes(), today=date(2026, 11, 8))
    own = docs.own_invoice(rec)
    assert own is not None
    inv = docs.take_over(rec["id"], own.cislo, own.customer, draft(), vs=own.vs)
    assert (inv["cislo"], inv["vs"], inv["zdroj"], inv["castka"]) == (
        "20260042",
        "20260042",
        "Air Bank",
        D("1250.00"),
    )
    assert docs.all() == []  # removed from the queue
    svc = InvoiceService(docs.storage, firma)
    pdf = svc.pdf_path(inv)
    assert pdf.read_bytes() == FIXTURE.read_bytes()  # original PDF kept
    contact = docs.storage.table(KONTAKTY_SCHEMA).get(inv["kontakt_id"])
    assert contact is not None and (contact["nazev"], contact["ulice"], contact["typ"]) == (
        "Petr Zákazník",
        "Lipová 3",
        "odběratel",
    )
    # The next invoice issued in the app continues the same series.
    nxt = svc.issue(
        draft(
            kontakt_id=inv["kontakt_id"],
            datum_vystaveni=date(2026, 11, 6),
            datum_splatnosti=date(2026, 11, 20),
        )
    )
    assert nxt["cislo"] == "20260043"
    with pytest.raises(InvoiceError, match="opravte ji tam"):
        svc.update(inv["cislo"], draft(kontakt_id=inv["kontakt_id"]))


def test_take_over_refuses_existing_number(docs: ReceivedDocs) -> None:
    first = docs.upload(FIXTURE.read_bytes(), today=date(2026, 11, 8))
    second = docs.upload(FIXTURE.read_bytes(), today=date(2026, 11, 8))
    docs.take_over(first["id"], "20260042", Customer(nazev="Petr Zákazník"), draft())
    with pytest.raises(ReceivedError, match="už v aplikaci je"):
        docs.take_over(second["id"], "20260042", Customer(nazev="Petr Zákazník"), draft())
    assert [d["id"] for d in docs.queue()] == [second["id"]]


@pytest.mark.parametrize(
    ("cislo", "kw", "message"),
    [
        ("2026-42", {}, "číselné řadě"),
        ("20250042", {}, "v roce 2025"),
        ("20260042", {"lines": []}, "aspoň jednu"),
    ],
)
def test_take_over_validation(
    docs: ReceivedDocs, cislo: str, kw: dict[str, object], message: str
) -> None:
    rec = docs.upload(FIXTURE.read_bytes(), today=date(2026, 11, 8))
    with pytest.raises(ReceivedError, match=message):
        docs.take_over(rec["id"], cislo, Customer(nazev="Petr Zákazník"), draft(**kw))


def test_customer_is_required(docs: ReceivedDocs) -> None:
    rec = docs.upload(FIXTURE.read_bytes(), today=date(2026, 11, 8))
    with pytest.raises(ReceivedError, match="odběratele"):
        docs.take_over(rec["id"], "20260042", Customer(), draft())


def test_only_own_invoices_can_be_taken_over(docs: ReceivedDocs) -> None:
    other = docs.upload(
        (FIXTURE.parent / "faktura-radky.pdf").read_bytes(), today=date(2026, 11, 8)
    )
    with pytest.raises(ReceivedError, match="nejde převzít"):
        docs.take_over(other["id"], "20260042", Customer(nazev="X"), draft())
