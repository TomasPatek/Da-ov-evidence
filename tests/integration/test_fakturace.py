"""Phase 1 through the web UI: contacts, jobs, invoices, PDF, ISDOC, e-mail."""

from __future__ import annotations

import io
import re
from datetime import date, timedelta
from pathlib import Path

import pdfplumber
import pytest
from fastapi.testclient import TestClient
from lxml import etree
from pyzbar.pyzbar import decode

from tests.conftest import FakeAres, FakeMailer, complete_wizard, get_csrf

XSD = Path(__file__).parents[1] / "fixtures" / "isdoc" / "isdoc-invoice-6.0.2.xsd"
TODAY = date.today()


@pytest.fixture
def ready(client: TestClient) -> TestClient:
    complete_wizard(client)
    return client


def token(client: TestClient) -> str:
    return get_csrf(client, "/nastaveni")


def new_contact(client: TestClient, **fields: str) -> str:
    data = {
        "csrf_token": token(client),
        "typ": "odběratel",
        "nazev": "Petr Zákazník",
        "ico": "",
        "dic": "",
        "ulice": "Dlouhá 1",
        "mesto": "Brno",
        "psc": "60200",
        "email": "petr@example.cz",
        "telefon": "",
        "poznamka": "",
        **fields,
    }
    resp = client.post("/kontakty/novy", data=data)
    assert resp.status_code == 303, resp.text
    return resp.headers["location"].rsplit("/", 1)[1]


def new_job(client: TestClient, kontakt: str, **fields: str) -> str:
    data = {
        "csrf_token": token(client),
        "kontakt_id": kontakt,
        "nazev": "Oprava střechy",
        "adresa_realizace": "Dlouhá 1, Brno",
        "stav": "rozpracováno",
        "datum_zalozeni": TODAY.isoformat(),
        "datum_dokonceni": "",
        "poznamka": "",
        **fields,
    }
    resp = client.post("/zakazky/nova", data=data)
    assert resp.status_code == 303, resp.text
    return resp.headers["location"].rsplit("/", 1)[1]


def issue(client: TestClient, kontakt: str, zakazka: str = "", **extra: object) -> str:
    data: dict[str, object] = {
        "csrf_token": token(client),
        "kontakt_id": kontakt,
        "zakazka_id": zakazka,
        "datum_vystaveni": TODAY.isoformat(),
        "datum_splatnosti": (TODAY + timedelta(days=14)).isoformat(),
        "poznamka": "Děkuji za zakázku.",
        "popis": ["Práce na střeše", "Střešní krytina", ""],
        "mnozstvi": ["8", "1,5", "1"],
        "jednotka": ["hod", "m²", "ks"],
        "cena": ["450", "333,33", ""],
        **extra,
    }
    resp = client.post("/faktury/nova", data=data)
    assert resp.status_code == 303, resp.text
    return resp.headers["location"].split("/")[2].split("?")[0]


# -- access ------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/kontakty", "/kontakty/novy", "/zakazky", "/zakazky/nova", "/faktury", "/faktury/nova"],
)
def test_pages_need_login(client: TestClient, path: str) -> None:
    complete_wizard(client)
    client.cookies.clear()
    resp = client.get(path)
    assert resp.status_code == 303
    assert "/prihlaseni" in resp.headers["location"]


def test_post_without_csrf_is_rejected(ready: TestClient) -> None:
    resp = ready.post("/kontakty/novy", data={"nazev": "X", "typ": "odběratel"})
    assert resp.status_code == 403


# -- contacts ----------------------------------------------------------------


def test_contact_from_ares(ready: TestClient) -> None:
    resp = ready.get("/kontakty/ares", params={"ico": "00006947", "typ": "odběratel"})
    assert "Ministerstvo financí" in resp.text
    assert 'name="ares_aktualizovano"' in resp.text
    resp = ready.get("/kontakty/ares", params={"ico": "12345678"})
    assert "kontrolní součet" in resp.text
    resp = ready.get("/kontakty/ares", params={"ico": "27074358"})
    assert "neexistuje" in resp.text


def test_contact_ares_down_is_reported(ready: TestClient, fake_ares: FakeAres) -> None:
    fake_ares.down = True
    assert "nedostupný" in ready.get("/kontakty/ares", params={"ico": "00006947"}).text


def test_contact_create_edit_refresh_delete(ready: TestClient, fake_ares: FakeAres) -> None:
    cid = new_contact(ready, ico="00006947", nazev="Staré jméno", ares_aktualizovano="2026-01-02")
    assert cid == "K0001"
    page = ready.get(f"/kontakty/{cid}").text
    assert "Staré jméno" in page
    assert "Naposledy 2. 1. 2026" in page

    # Duplicate IČO is reported.
    resp = ready.post(
        "/kontakty/novy",
        data={
            "csrf_token": token(ready),
            "typ": "odběratel",
            "nazev": "Dvojník",
            "ico": "00006947",
        },
    )
    assert resp.status_code == 400
    assert "už existuje" in resp.text

    resp = ready.post(
        f"/kontakty/{cid}",
        data={
            "csrf_token": token(ready),
            "typ": "obojí",
            "nazev": "Nové jméno",
            "ico": "00006947",
            "email": "spatne",
        },
    )
    assert resp.status_code == 400
    assert "E-mail" in resp.text
    resp = ready.post(
        f"/kontakty/{cid}",
        data={"csrf_token": token(ready), "typ": "obojí", "nazev": "Nové jméno", "ico": "00006947"},
    )
    assert resp.status_code == 303
    assert "Nové jméno" in ready.get("/kontakty").text

    resp = ready.post(f"/kontakty/{cid}/ares", data={"csrf_token": token(ready)})
    assert "Ministerstvo financí" in resp.text
    assert "aktualizovány z ARES" in resp.text

    resp = ready.post(f"/kontakty/{cid}/smazat", data={"csrf_token": token(ready)})
    assert resp.status_code == 303
    assert ready.get(f"/kontakty/{cid}").status_code == 404


def test_contact_search_and_filter(ready: TestClient) -> None:
    new_contact(ready, nazev="Alfa s.r.o.")
    new_contact(ready, nazev="Beta dodavatel", typ="dodavatel", email="beta@example.cz")
    page = ready.get("/kontakty", params={"q": "alfa"}).text
    assert "Alfa s.r.o." in page and "Beta dodavatel" not in page
    page = ready.get("/kontakty", params={"typ": "dodavatel"}).text
    assert "Beta dodavatel" in page and "Alfa s.r.o." not in page


def test_contact_with_invoice_cannot_be_deleted(ready: TestClient) -> None:
    cid = new_contact(ready)
    issue(ready, cid)
    resp = ready.post(f"/kontakty/{cid}/smazat", data={"csrf_token": token(ready)})
    assert resp.status_code == 400
    assert "nejde smazat" in resp.text


def test_contact_save_and_continue(ready: TestClient) -> None:
    resp = ready.post(
        "/kontakty/novy",
        data={"csrf_token": token(ready), "typ": "odběratel", "nazev": "Rychlý", "dal": "faktura"},
    )
    assert resp.headers["location"] == "/faktury/nova?kontakt=K0001"


# -- jobs ----------------------------------------------------------------------


def test_job_create_and_warnings(ready: TestClient) -> None:
    cid = new_contact(ready)
    jid = new_job(ready, cid)
    assert jid == f"Z{TODAY.year}-001"
    assert new_job(ready, cid, nazev="Druhá") == f"Z{TODAY.year}-002"
    resp = ready.post(
        f"/zakazky/{jid}",
        data={
            "csrf_token": token(ready),
            "kontakt_id": cid,
            "nazev": "Oprava střechy",
            "stav": "dokončeno",
            "datum_zalozeni": TODAY.isoformat(),
        },
    )
    assert resp.status_code == 303
    detail = ready.get(f"/zakazky/{jid}").text
    assert "dokončená, ale nemá fakturu" in detail
    assert TODAY.isoformat() in detail  # completion date filled in automatically
    assert "Dokončené bez faktury" in ready.get("/").text


def test_job_validation(ready: TestClient) -> None:
    resp = ready.post(
        "/zakazky/nova",
        data={
            "csrf_token": token(ready),
            "kontakt_id": "K404",
            "nazev": "",
            "stav": "x",
            "datum_zalozeni": "zitra",
        },
    )
    assert resp.status_code == 400
    for msg in ("Vyberte zákazníka", "Vyplňte název", "Neznámý stav", "nemá platný tvar"):
        assert msg in resp.text


def test_new_job_prefills_address(ready: TestClient) -> None:
    cid = new_contact(ready)
    assert "Dlouhá 1, Brno" in ready.get("/zakazky/nova", params={"kontakt": cid}).text


# -- invoices --------------------------------------------------------------------


def test_issue_invoice_end_to_end(ready: TestClient, settings: object) -> None:
    cid = new_contact(ready)
    jid = new_job(ready, cid)
    form = ready.get("/faktury/nova", params={"zakazka": jid}).text
    assert f'value="{jid}" selected' in form
    assert (TODAY + timedelta(days=14)).isoformat() in form

    cislo = issue(ready, cid, jid)
    assert cislo == f"{TODAY.year}0001"
    detail = ready.get(f"/faktury/{cislo}").text
    assert "4\xa0100,00" in detail
    assert "vystavena" in detail
    assert f"/faktury/{cislo}/qr.svg" in detail
    assert "vyfakturováno" in ready.get(f"/zakazky/{jid}").text
    assert cislo in ready.get("/faktury").text


def test_invoice_pdf_contains_mandatory_data_and_readable_qr(ready: TestClient) -> None:
    cid = new_contact(ready, ico="00006947", nazev="Ministerstvo financí")
    cislo = issue(ready, cid)
    resp = ready.get(f"/faktury/{cislo}/pdf")
    assert resp.headers["content-type"] == "application/pdf"
    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        assert len(pdf.pages) == 1
        page = pdf.pages[0]
        text = page.extract_text().replace("\xa0", " ")
        image = page.to_image(resolution=200).original
    for expected in (
        f"Faktura {cislo}",
        "Jan Testovací",  # supplier
        "IČO: 00006947",
        "Zapsán v živnostenském rejstříku.",
        "Ministerstvo financí",
        "Nejsem plátce DPH.",
        "19-2000145399/0800",
        "4 100,00 Kč",
        "Děkuji za zakázku.",
    ):
        assert expected in text, expected
    codes = decode(image)
    assert len(codes) == 1
    payload = codes[0].data.decode()
    assert payload.startswith("SPD*1.0*ACC:CZ6508000000192000145399*AM:4100.00*CC:CZK")
    assert f"*X-VS:{cislo}" in payload


def test_pdf_is_regenerated_when_missing(ready: TestClient, settings: object) -> None:
    cid = new_contact(ready)
    cislo = issue(ready, cid)
    pdf = Path(settings.data_dir) / cislo[:4] / "doklady" / f"{cislo}.pdf"  # type: ignore[attr-defined]
    assert pdf.exists()
    pdf.unlink()
    assert ready.get(f"/faktury/{cislo}/pdf").content.startswith(b"%PDF")
    assert pdf.exists()


def test_isdoc_is_valid(ready: TestClient) -> None:
    cid = new_contact(ready, ico="00006947", dic="CZ00006947")
    cislo = issue(ready, cid)
    resp = ready.get(f"/faktury/{cislo}/isdoc")
    assert "attachment" in resp.headers["content-disposition"]
    schema = etree.XMLSchema(etree.parse(str(XSD)))
    doc = etree.fromstring(resp.content)
    assert schema.validate(doc), schema.error_log
    ns = {"i": "http://isdoc.cz/namespace/2013"}
    assert doc.findtext("i:ID", namespaces=ns) == cislo
    assert doc.findtext("i:VATApplicable", namespaces=ns) == "false"
    assert doc.findtext("i:LegalMonetaryTotal/i:PayableAmount", namespaces=ns) == "4100.00"
    assert doc.findtext(".//i:VariableSymbol", namespaces=ns) == cislo
    assert len(doc.findall("i:InvoiceLines/i:InvoiceLine", namespaces=ns)) == 2


def test_isdoc_for_private_person_is_valid(ready: TestClient) -> None:
    cid = new_contact(ready)  # no IČO
    cislo = issue(ready, cid)
    schema = etree.XMLSchema(etree.parse(str(XSD)))
    assert schema.validate(etree.fromstring(ready.get(f"/faktury/{cislo}/isdoc").content))


def test_issue_form_errors_keep_input(ready: TestClient) -> None:
    cid = new_contact(ready)
    resp = ready.post(
        "/faktury/nova",
        data={
            "csrf_token": token(ready),
            "kontakt_id": cid,
            "datum_vystaveni": TODAY.isoformat(),
            "datum_splatnosti": TODAY.isoformat(),
            "popis": ["Práce", "Něco"],
            "mnozstvi": ["x", "1"],
            "jednotka": ["hod", "ks"],
            "cena": ["100", "abc"],
        },
    )
    assert resp.status_code == 400
    assert "Položka 1: množství není číslo" in resp.text
    assert "Položka 2: cena není platná" in resp.text
    assert 'value="Práce"' in resp.text
    assert ready.get("/faktury").text.count("/faktury/2") == 0


def test_issue_requires_lines(ready: TestClient) -> None:
    cid = new_contact(ready)
    resp = ready.post(
        "/faktury/nova",
        data={
            "csrf_token": token(ready),
            "kontakt_id": cid,
            "datum_vystaveni": TODAY.isoformat(),
            "datum_splatnosti": TODAY.isoformat(),
        },
    )
    assert resp.status_code == 400
    assert "aspoň jednu položku" in resp.text


def test_live_total_and_extra_row(ready: TestClient) -> None:
    resp = ready.post(
        "/faktury/soucet",
        data={
            "popis": ["A", "B", ""],
            "mnozstvi": ["2", "1,5", "1"],
            "jednotka": ["ks"] * 3,
            "cena": ["100", "10", ""],
        },
        headers={"X-CSRF-Token": token(ready)},
    )
    assert "215,00" in resp.text
    assert 'name="popis"' in ready.get("/faktury/radek").text


def test_pay_unpay_and_cancel(ready: TestClient) -> None:
    cid = new_contact(ready)
    jid = new_job(ready, cid)
    cislo = issue(ready, cid, jid)
    future = (TODAY + timedelta(days=1)).isoformat()
    resp = ready.post(
        f"/faktury/{cislo}/uhrazena", data={"csrf_token": token(ready), "datum_uhrady": future}
    )
    assert resp.status_code == 400
    assert "budoucnosti" in resp.text
    resp = ready.post(
        f"/faktury/{cislo}/uhrazena",
        data={"csrf_token": token(ready), "datum_uhrady": TODAY.isoformat()},
    )
    assert resp.status_code == 303
    assert "uhrazena" in ready.get(f"/faktury/{cislo}").text
    assert "uhrazeno" in ready.get(f"/zakazky/{jid}").text
    assert (
        ready.post(f"/faktury/{cislo}/neuhrazena", data={"csrf_token": token(ready)}).status_code
        == 303
    )

    resp = ready.post(f"/faktury/{cislo}/storno", data={"csrf_token": token(ready), "duvod": ""})
    assert resp.status_code == 400
    resp = ready.post(
        f"/faktury/{cislo}/storno", data={"csrf_token": token(ready), "duvod": "Omyl"}
    )
    assert resp.status_code == 303
    page = ready.get(f"/faktury/{cislo}").text
    assert "Stornováno: Omyl" in page
    assert "qr.svg" not in page
    assert ready.get(f"/faktury/{cislo}/qr.svg").status_code == 404
    # The number is kept: the next invoice continues the series.
    assert issue(ready, cid) == f"{TODAY.year}0002"


def test_overdue_invoice_on_dashboard(ready: TestClient) -> None:
    cid = new_contact(ready)
    past = TODAY - timedelta(days=30)
    cislo = issue(
        ready,
        cid,
        datum_vystaveni=past.isoformat(),
        datum_splatnosti=(past + timedelta(days=14)).isoformat(),
    )
    home = ready.get("/").text
    assert "Po splatnosti" in home
    assert cislo in home
    assert "po splatnosti" in ready.get("/faktury").text


def test_send_invoice(ready: TestClient, fake_mailer: FakeMailer) -> None:
    cid = new_contact(ready)
    cislo = issue(ready, cid)
    form = ready.get(f"/faktury/{cislo}/odeslat").text
    assert 'value="petr@example.cz"' in form
    resp = ready.post(
        f"/faktury/{cislo}/odeslat",
        data={
            "csrf_token": token(ready),
            "komu": "petr@example.cz",
            "predmet": f"Faktura {cislo}",
            "text": "Dobrý den",
            "isdoc": "1",
        },
    )
    assert resp.status_code == 303
    (msg,) = fake_mailer.sent
    assert msg["To"] == "petr@example.cz"
    assert msg["Subject"] == f"Faktura {cislo}"
    assert "fakturace@example.cz" in msg["From"]
    names = [p.get_filename() for p in msg.iter_attachments()]
    assert names == [f"faktura-{cislo}.pdf", f"faktura-{cislo}.isdoc"]
    pdf = next(msg.iter_attachments()).get_content()
    assert pdf.startswith(b"%PDF")
    detail = ready.get(f"/faktury/{cislo}").text
    assert "odeslana" in detail
    assert "Odesláno" in detail


def test_send_failure_keeps_state(ready: TestClient, fake_mailer: FakeMailer) -> None:
    fake_mailer.fail = True
    cid = new_contact(ready)
    cislo = issue(ready, cid)
    resp = ready.post(
        f"/faktury/{cislo}/odeslat",
        data={"csrf_token": token(ready), "komu": "petr@example.cz", "predmet": "x", "text": ""},
    )
    assert resp.status_code == 400
    assert "nepovedlo" in resp.text
    assert re.search(r"badge-vystavena", ready.get(f"/faktury/{cislo}").text)


def test_send_without_smtp_explains_setup(ready: TestClient, fake_mailer: FakeMailer) -> None:
    fake_mailer.configured = False
    cid = new_contact(ready)
    cislo = issue(ready, cid)
    page = ready.get(f"/faktury/{cislo}/odeslat").text
    assert "není nastavené" in page
    assert "SMTP_" in page


def test_unknown_invoice_is_404(ready: TestClient) -> None:
    assert ready.get("/faktury/20269999").status_code == 404
    assert ready.get("/faktury/nesmysl/pdf").status_code == 404


def test_numbering_format_locked_after_first_invoice(ready: TestClient) -> None:
    issue(ready, new_contact(ready))
    resp = ready.post(
        "/pruvodce/rada",
        data={
            "csrf_token": token(ready),
            "format_cisla": "RRRRNNN",
            "pocatecni_cislo": "1",
            "splatnost_dni": "14",
            "text_dph": "Nejsem plátce DPH.",
        },
    )
    assert resp.status_code == 400
    assert "nejde změnit" in resp.text
