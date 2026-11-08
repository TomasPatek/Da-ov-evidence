"""Received documents: upload, queue, confirmation, payment into the cash book."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import FirmaConfig
from app.contacts import KONTAKTY_SCHEMA
from app.ingest.files import UploadError
from app.jobs import ZAKAZKY_SCHEMA
from app.journal import Journal, PaymentMethod
from app.received import Confirmation, ReceivedDocs, ReceivedError
from app.storage import Storage

FIXTURES = Path(__file__).parents[1] / "fixtures" / "doklady"
D = Decimal
TODAY = date(2027, 5, 1)


@pytest.fixture
def firma() -> FirmaConfig:
    cfg = FirmaConfig()
    cfg.firma.ico = "99999994"
    cfg.banka.ucet = "1234567899/0100"
    cfg.evidence.zacatek = "2027-01-01"
    return cfg


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    s = Storage(tmp_path / "data")
    s.table(ZAKAZKY_SCHEMA).insert(
        {
            "id": "Z2027-001",
            "kontakt_id": "K0001",
            "nazev": "Oprava trouby",
            "adresa_realizace": "Lipová 3",
            "stav": "rozpracováno",
            "datum_zalozeni": date(2027, 1, 2),
            "datum_dokonceni": None,
            "poznamka": "",
        }
    )
    return s


@pytest.fixture
def docs(storage: Storage, firma: FirmaConfig) -> ReceivedDocs:
    return ReceivedDocs(storage, firma)


def confirmation(**kw: object) -> Confirmation:
    base: dict[str, object] = dict(
        typ="faktura",
        dodavatel_ico="99990032",
        dodavatel_nazev="Díly Vzor s.r.o.",
        cislo_dodavatele="2027000123",
        datum_vystaveni=date(2027, 1, 5),
        datum_splatnosti=date(2027, 1, 19),
        castka=D("1500.00"),
        vs="2027000123",
        ucet="19-2000145399/0800",
        popis="Topné těleso",
        kategorie=15,
        zakazka_id="Z2027-001",
        zpusob_uhrady="převod",
        datum_uhrady=None,
    )
    base.update(kw)
    return Confirmation(**base)  # type: ignore[arg-type]


def test_upload_reads_and_queues(docs: ReceivedDocs, storage: Storage) -> None:
    rec = docs.upload((FIXTURES / "faktura-radky.pdf").read_bytes(), today=TODAY)
    assert rec["id"] == "PD2027-001"
    assert rec["stav"] == "ke kontrole"
    assert rec["castka"] == D("1500.00")
    assert rec["dodavatel_ico"] == "99990032"
    assert rec["zakazka_id"] == "Z2027-001"  # the only running job is suggested
    assert "kategorie" in rec["nejista_pole"]
    assert (storage.data_dir / "2027" / "doklady" / "PD2027-001.pdf").exists()
    assert [d["id"] for d in docs.queue()] == ["PD2027-001"]


def test_upload_paid_by_card_prefills_payment(docs: ReceivedDocs) -> None:
    rec = docs.upload((FIXTURES / "faktura-sloupce.pdf").read_bytes(), today=TODAY)
    assert rec["zpusob_uhrady"] == "karta"
    assert rec["datum_uhrady"] == date(2027, 2, 14)
    assert "datum_uhrady" in rec["nejista_pole"]


def test_upload_rejects_unknown_type(docs: ReceivedDocs) -> None:
    with pytest.raises(UploadError):
        docs.upload(b"MZ\x90\x00", today=TODAY)
    assert docs.all() == []


def test_confirm_creates_supplier_and_learns_template(docs: ReceivedDocs, storage: Storage) -> None:
    rec = docs.upload((FIXTURES / "faktura-radky.pdf").read_bytes(), today=TODAY)
    done = docs.confirm(rec["id"], confirmation(kategorie=19))
    assert done["stav"] == "potvrzen"
    assert done["nejista_pole"] == ""
    contact = storage.table(KONTAKTY_SCHEMA).get(done["kontakt_id"])
    assert contact is not None and contact["typ"] == "dodavatel" and contact["ico"] == "99990032"
    assert docs.templates.get("99990032")["kategorie"] == 19  # type: ignore[index]
    # The next document from the same supplier gets the learned category and contact.
    again = docs.upload((FIXTURES / "faktura-radky.pdf").read_bytes(), today=TODAY)
    assert again["kategorie"] == 19
    assert again["kontakt_id"] == done["kontakt_id"]
    assert "kategorie" not in again["nejista_pole"]


def test_confirm_with_payment_writes_expense(
    docs: ReceivedDocs, storage: Storage, firma: FirmaConfig
) -> None:
    rec = docs.upload((FIXTURES / "faktura-sloupce.pdf").read_bytes(), today=TODAY)
    done = docs.confirm(
        rec["id"],
        confirmation(
            dodavatel_ico="99990041",
            dodavatel_nazev="Spotřebiče Pokus s.r.o.",
            castka=D("829.00"),
            zpusob_uhrady="karta",
            datum_uhrady=date(2027, 2, 14),
            popis="Ohřívač vody",
        ),
        today=TODAY,
    )
    assert done["stav"] == "uhrazen"
    (row,) = Journal(storage, firma).entries(2027)
    assert (row["smer"], row["ucet"], row["kategorie"], row["castka"]) == (
        "výdaj",
        "banka",
        15,
        D("829.00"),
    )
    assert row["cislo_dokladu"] == rec["id"]
    assert row["zakazka_id"] == "Z2027-001"
    assert row["popis"] == "Ohřívač vody – Spotřebiče Pokus s.r.o."
    # Editing the paid document replaces the cash book row.
    docs.confirm(
        rec["id"],
        confirmation(castka=D("830.00"), zpusob_uhrady="hotovost", datum_uhrady=date(2027, 2, 15)),
        today=TODAY,
    )
    (row,) = Journal(storage, firma).entries(2027)
    assert (row["ucet"], row["castka"], row["cislo_dokladu"]) == (
        "hotovost",
        D("830.00"),
        "VPD1/27",
    )


def test_pay_later_and_undo(docs: ReceivedDocs, storage: Storage, firma: FirmaConfig) -> None:
    rec = docs.confirm(None, confirmation())
    assert rec["zdroj"] == "ručně" and rec["soubor"] == ""
    docs.pay(rec["id"], date(2027, 1, 18), PaymentMethod.TRANSFER)
    assert len(Journal(storage, firma).entries(2027)) == 1
    back = docs.unpay(rec["id"])
    assert back["stav"] == "potvrzen"
    assert Journal(storage, firma).entries(2027) == []


def test_pay_requires_review_first(docs: ReceivedDocs) -> None:
    rec = docs.upload((FIXTURES / "faktura-radky.pdf").read_bytes(), today=TODAY)
    with pytest.raises(ReceivedError, match="zkontrolujte"):
        docs.pay(rec["id"], date(2027, 1, 18), PaymentMethod.TRANSFER)


def test_payment_before_start_is_not_journaled(
    docs: ReceivedDocs, storage: Storage, firma: FirmaConfig
) -> None:
    rec = docs.confirm(
        None,
        confirmation(datum_vystaveni=date(2026, 12, 20), datum_uhrady=date(2026, 12, 28)),
        today=TODAY,
    )
    assert rec["stav"] == "uhrazen"
    assert Journal(storage, firma).entries(2026) == []


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"dodavatel_nazev": ""}, "dodavatele"),
        ({"dodavatel_ico": "12345678"}, "kontrolní"),
        ({"datum_vystaveni": None}, "datum vystavení"),
        ({"castka": D("0")}, "kladná"),
        ({"kategorie": 9}, "kategorii"),
        ({"zpusob_uhrady": "šekem"}, "způsob"),
        ({"zakazka_id": "Z9"}, "Zakázka"),
    ],
)
def test_validation(docs: ReceivedDocs, kw: dict[str, object], message: str) -> None:
    with pytest.raises(ReceivedError, match=message):
        docs.confirm(None, confirmation(**kw))


def test_existing_customer_becomes_both(docs: ReceivedDocs, storage: Storage) -> None:
    storage.table(KONTAKTY_SCHEMA).insert(
        {
            "id": "K0001",
            "typ": "odběratel",
            "ico": "99990032",
            "dic": "",
            "nazev": "Díly Vzor s.r.o.",
            "ulice": "",
            "mesto": "",
            "psc": "",
            "email": "",
            "telefon": "",
            "poznamka": "",
            "ares_aktualizovano": None,
        }
    )
    rec = docs.confirm(None, confirmation())
    assert rec["kontakt_id"] == "K0001"
    assert storage.table(KONTAKTY_SCHEMA).get("K0001")["typ"] == "obojí"  # type: ignore[index]


def test_discard_only_in_queue(docs: ReceivedDocs, storage: Storage) -> None:
    rec = docs.upload((FIXTURES / "uctenka-qr.png").read_bytes(), today=TODAY)
    path = docs.file_path(rec)
    assert path is not None and path.exists()
    docs.discard(rec["id"])
    assert not path.exists() and docs.all() == []
    kept = docs.confirm(None, confirmation())
    with pytest.raises(ReceivedError):
        docs.discard(kept["id"])


def test_file_path_stays_inside_documents_folder(docs: ReceivedDocs) -> None:
    rec = docs.confirm(None, confirmation())
    rec["soubor"] = "../../config/auth.json"
    assert docs.file_path(rec) is None


def test_payment_with_transaction_code(
    docs: ReceivedDocs, storage: Storage, firma: FirmaConfig
) -> None:
    rec = docs.confirm(None, confirmation())
    docs.pay(rec["id"], date(2027, 1, 18), PaymentMethod.CARD, kod_transakce="4455667788")
    (row,) = Journal(storage, firma).entries(2027)
    assert row["cislo_dokladu"] == "4455667788"
    docs.unpay(rec["id"])
    done = docs.confirm(
        None, confirmation(datum_uhrady=date(2027, 1, 20), kod_transakce="111"), today=TODAY
    )
    assert Journal(storage, firma).for_document(done["id"])[0]["cislo_dokladu"] == "111"
