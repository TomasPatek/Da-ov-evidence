"""Reading received documents: golden files over fictional samples plus rule tests."""

from __future__ import annotations

import io
import json
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from app.ingest.files import ISDOC, ISDOCX, JPEG, PDF, PNG, UploadError, detect, isdoc_from_isdocx
from app.ingest.isdoc import parse_isdoc
from app.ingest.model import Extraction
from app.ingest.pdftext import extract_text_fields, normalize
from app.ingest.pipeline import complete, read_document
from app.ingest.qr import parse_spayd
from app.ingest.templates import SupplierTemplates

FIXTURES = Path(__file__).parents[1] / "fixtures" / "doklady"
SAMPLES = sorted(p for p in FIXTURES.iterdir() if p.suffix != ".json")
OWN_ICO, OWN_ACCOUNT, OWN_IBAN = "99999994", "1000000005/3030", "CZ0330300000001000000005"


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.name)
def test_golden_files(path: Path, tmp_path: Path) -> None:
    data = path.read_bytes()
    ex = read_document(
        data, detect(data), OWN_ICO, OWN_ACCOUNT, SupplierTemplates(tmp_path), [], [], OWN_IBAN
    )
    golden = json.loads((FIXTURES / f"{path.name}.json").read_text("utf-8"))
    assert ex.as_json() == golden["values"]
    assert sorted(ex.uncertain) == golden["uncertain"]
    assert ex.steps == golden["steps"]


def test_samples_never_contain_own_company_as_supplier() -> None:
    for golden in FIXTURES.glob("*.json"):
        values = json.loads(golden.read_text("utf-8"))["values"]
        assert values.get("dodavatel_ico") != OWN_ICO
        assert values.get("ucet") != OWN_ACCOUNT


# -- file types -------------------------------------------------------------------


def test_detect_by_content() -> None:
    assert detect(b"%PDF-1.7 ...") is PDF
    assert detect(b"\xff\xd8\xff\xe0 jpeg") is JPEG
    assert detect(b"\x89PNG\r\n\x1a\n...") is PNG
    assert detect((FIXTURES / "faktura.isdoc").read_bytes()) is ISDOC
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("faktura.isdoc", (FIXTURES / "faktura.isdoc").read_bytes())
    assert detect(buf.getvalue()) is ISDOCX
    assert isdoc_from_isdocx(buf.getvalue()) == (FIXTURES / "faktura.isdoc").read_bytes()


@pytest.mark.parametrize(
    "data",
    [b"", b"MZ\x90\x00 exe", b"<?xml version='1.0'?><html/>", b"PK\x03\x04broken", b"GIF89a"],
)
def test_detect_rejects(data: bytes) -> None:
    with pytest.raises(UploadError):
        detect(data)


def test_isdoc_rejects_entities() -> None:
    evil = b"""<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>
    <Invoice xmlns="http://isdoc.cz/namespace/2013"><ID>&a;</ID></Invoice>"""
    ex = Extraction()
    assert parse_isdoc(evil, ex) is False
    assert ex.values == {}


def test_isdoc_paid_in_advance() -> None:
    xml = (
        (FIXTURES / "faktura.isdoc")
        .read_bytes()
        .replace(b"<PayableAmount>3630.00</PayableAmount>", b"<PayableAmount>0.00</PayableAmount>")
    )
    ex = Extraction()
    assert parse_isdoc(xml, ex)
    assert ex.get("uhrazeno_predem") is True
    assert str(ex.get("castka")) == "3630.00"


# -- text rules ---------------------------------------------------------------------


def text_fields(text: str) -> Extraction:
    ex = Extraction()
    extract_text_fields(normalize(text), ex, OWN_ICO, OWN_ACCOUNT)
    return ex


def test_own_company_is_skipped() -> None:
    ex = text_fields("Odběratel IČO: 99999994\nDodavatel: Firma s.r.o. IČO: 99990008\nCelkem 10,00")
    assert ex.get("dodavatel_ico") == "99990008"


def test_amount_with_thousands_and_label_variants() -> None:
    assert str(text_fields("K úhradě: 12 345,60 Kč").get("castka")) == "12345.60"
    assert str(text_fields("Celkem bez DPH 100,00\nCelkem s DPH 121,00").get("castka")) == "121.00"
    ex = text_fields("Položka 5,00\nPoložka 70,00")
    assert str(ex.get("castka")) == "70.00"
    assert "castka" in ex.uncertain


def test_dates_on_one_line_are_certain() -> None:
    ex = text_fields("Datum vystavení: 1. 2. 2027\nDatum splatnosti: 15.02.2027")
    assert ex.get("datum_vystaveni").isoformat() == "2027-02-01"
    assert ex.get("datum_splatnosti").isoformat() == "2027-02-15"
    assert not ex.uncertain & {"datum_vystaveni", "datum_splatnosti"}


def test_invalid_date_is_ignored() -> None:
    assert text_fields("Datum vystavení: 31.02.2027").get("datum_vystaveni") is None


def test_payment_hints() -> None:
    assert text_fields("Způsob úhrady: hotově").get("zpusob_uhrady") == "hotovost"
    assert text_fields("Uhrazeno platební kartou").get("zpusob_uhrady") == "karta"
    assert text_fields("Forma úhrady: převodem").get("zpusob_uhrady") == "převod"


def test_spayd_parser() -> None:
    fields = parse_spayd("SPD*1.0*ACC:CZ6508000000192000145399*AM:10.00*MSG:A%2AB")
    assert fields == {"ACC": "CZ6508000000192000145399", "AM": "10.00", "MSG": "A*B"}
    assert parse_spayd("https://example.cz") is None


# -- templates, contacts, jobs ---------------------------------------------------------


def test_template_is_learned_and_applied(tmp_path: Path) -> None:
    tpl = SupplierTemplates(tmp_path)
    tpl.learn("99990032", {"kategorie": 19, "popis": "Telefon", "kontakt_id": "K0003", "vs": "1"})
    assert tpl.get("99990032") == {"kategorie": 19, "popis": "Telefon", "kontakt_id": "K0003"}
    data = (FIXTURES / "faktura-radky.pdf").read_bytes()
    ex = read_document(data, PDF, OWN_ICO, OWN_ACCOUNT, tpl, [], [])
    assert ex.get("kategorie") == 19
    assert "kategorie" not in ex.uncertain
    assert ex.get("popis") == "Telefon" and "popis" in ex.uncertain
    assert "šablona dodavatele" in ex.steps


def test_broken_template_file_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "sablony-dodavatelu.json").write_text("{nonsense", encoding="utf-8")
    assert SupplierTemplates(tmp_path).get("99990032") is None


def test_known_contact_and_job_suggestion() -> None:
    ex = Extraction(text="dodávka na adresu lipová 3, vzorov")
    ex.offer("dodavatel_ico", "99990008", "x")
    contacts = [{"id": "K0003", "ico": "99990008", "nazev": "Stavebniny Vzor s.r.o."}]
    jobs = [
        {
            "id": "Z2027-001",
            "stav": "rozpracováno",
            "nazev": "Oprava střechy",
            "adresa_realizace": "Lipová 3, Vzorov",
        },
        {
            "id": "Z2027-002",
            "stav": "rozpracováno",
            "nazev": "Koupelna",
            "adresa_realizace": "Náměstí 1",
        },
    ]
    complete(ex, contacts, jobs)
    assert ex.get("kontakt_id") == "K0003"
    assert ex.get("dodavatel_nazev") == "Stavebniny Vzor s.r.o."
    assert ex.get("zakazka_id") == "Z2027-001"
    assert "zakazka_id" in ex.uncertain


def test_single_running_job_is_suggested() -> None:
    ex = Extraction()
    complete(
        ex,
        [],
        [
            {"id": "Z1", "stav": "rozpracováno", "nazev": "X", "adresa_realizace": ""},
            {"id": "Z2", "stav": "uhrazeno", "nazev": "Y", "adresa_realizace": ""},
        ],
    )
    assert ex.get("zakazka_id") == "Z1"


# -- own invoices issued elsewhere ------------------------------------------------------


def test_own_invoice_is_recognised(tmp_path: Path) -> None:
    from app.ingest.own_invoice import customer_block

    data = (FIXTURES / "vydana-airbank.pdf").read_bytes()
    customer = customer_block(data, OWN_ICO)
    assert (customer.nazev, customer.ulice, customer.psc, customer.mesto) == (
        "Petr Zákazník",
        "Lipová 3",
        "54321",
        "Vzorov",
    )


def test_supplier_invoice_mentioning_our_ico_is_not_own(tmp_path: Path) -> None:
    # Received invoices carry our IČO as the customer, but ask for payment elsewhere.
    for name in ("faktura-radky.pdf", "faktura-sloupce.pdf", "faktura-qr.pdf"):
        data = (FIXTURES / name).read_bytes()
        ex = read_document(
            data, PDF, OWN_ICO, OWN_ACCOUNT, SupplierTemplates(tmp_path), [], [], OWN_IBAN
        )
        assert ex.get("typ") != "vydaná faktura", name


def test_own_ico_without_own_account_is_not_own() -> None:
    from app.ingest.own_invoice import is_own_document

    ex = Extraction(text="Dodavatel IČO: 99999994\nÚčet 19-2000145399/0800")
    assert not is_own_document(ex, OWN_ICO, OWN_ACCOUNT, OWN_IBAN)
    ex = Extraction(text="IČO: 99999994\nČíslo účtu: 1000000005/3030")
    assert is_own_document(ex, OWN_ICO, OWN_ACCOUNT, OWN_IBAN)


@pytest.mark.parametrize("space", [" ", " ", " "])
def test_amounts_with_no_break_space_thousands(space: str) -> None:
    from app.ingest.pdftext import _total, normalize

    lines = normalize(f"Celkem k úhradě: 12{space}345,60 Kč").split("\n")
    assert _total(lines) == (Decimal("12345.60"), True)


def test_paid_label_of_air_bank_cash_invoice() -> None:
    from app.ingest.pdftext import _total

    assert _total(["Zaplaceno: 1 150,00 Kč", "+420 600 000 000"]) == (Decimal("1150.00"), True)
    assert _total(["Celkem zaplaťte: 4 000,00 Kč"]) == (Decimal("4000.00"), True)


def test_parse_amount_ignores_no_break_spaces() -> None:
    from app.ingest.pdftext import parse_amount

    assert parse_amount("1 150,00") == Decimal("1150.00")
    assert parse_amount("12 345,60") == Decimal("12345.60")
