"""Phase 2 through the web UI: received documents, review queue, cash book, jobs."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FakeAres, complete_wizard, get_csrf
from tests.integration.test_fakturace import issue, new_contact, new_job

FIXTURES = Path(__file__).parents[1] / "fixtures" / "doklady"
TODAY = date.today()


@pytest.fixture
def ready(client: TestClient) -> TestClient:
    complete_wizard(client)  # cash book starts 1. 1. 2026 with 1 000 Kč cash, 50 000 Kč bank
    return client


def token(client: TestClient) -> str:
    return get_csrf(client, "/nastaveni")


def upload(client: TestClient, *names: str) -> str:
    files = [
        ("soubory", (n, (FIXTURES / n).read_bytes(), "application/octet-stream")) for n in names
    ]
    resp = client.post("/doklady/nahrat", data={"csrf_token": token(client)}, files=files)
    assert resp.status_code == 303, resp.text
    return resp.headers["location"]


def confirm_data(client: TestClient, **kw: str) -> dict[str, str]:
    data = {
        "csrf_token": token(client),
        "typ": "faktura",
        "dodavatel_ico": "99990032",
        "dodavatel_nazev": "Díly Vzor s.r.o.",
        "cislo_dodavatele": "2027000123",
        "datum_vystaveni": TODAY.isoformat(),
        "datum_splatnosti": "",
        "castka": "1 500,00",
        "vs": "",
        "ucet": "",
        "popis": "Topné těleso",
        "kategorie": "15",
        "zakazka_id": "",
        "zpusob_uhrady": "převod",
        "datum_uhrady": TODAY.isoformat(),
        "poznamka": "",
    }
    data.update(kw)
    return data


@pytest.mark.parametrize(
    "path", ["/doklady", "/doklady/novy", "/denik", "/denik/novy", "/denik/et328"]
)
def test_pages_need_login(client: TestClient, path: str) -> None:
    complete_wizard(client)
    client.cookies.clear()
    resp = client.get(path)
    assert resp.status_code == 303 and "/prihlaseni" in resp.headers["location"]


def test_upload_review_confirm_and_pay(ready: TestClient) -> None:
    location = upload(ready, "faktura-radky.pdf")
    doc_id = location.rsplit("/", 1)[1]
    page = ready.get(location).text
    assert "ke kontrole" in page
    assert 'value="1500,00"' in page
    assert 'value="2027000123"' in page
    assert f"/doklady/{doc_id}/nahled.png?strana=1" in page
    assert "uncertain" in page  # category and supplier name are highlighted
    preview = ready.get(f"/doklady/{doc_id}/nahled.png?strana=1")
    assert preview.headers["content-type"] == "image/png"
    assert preview.content.startswith(b"\x89PNG")
    assert ready.get(f"/doklady/{doc_id}/nahled.png?strana=9").status_code == 404
    original = ready.get(f"/doklady/{doc_id}/soubor")
    assert original.content.startswith(b"%PDF")
    assert "attachment" in original.headers["content-disposition"]

    data = confirm_data(ready, uhrazeno="1")
    resp = ready.post(location, data=data)
    assert resp.status_code == 303
    detail = ready.get(f"/doklady/{doc_id}").text
    assert "uhrazen" in detail
    journal = ready.get("/denik").text
    assert doc_id in journal and "Topné těleso – Díly Vzor s.r.o." in journal
    assert "48\xa0500,00" in journal  # bank: 50 000 - 1 500


def test_multiple_upload_goes_to_queue_and_rejects_bad_files(ready: TestClient) -> None:
    assert upload(ready, "faktura-sloupce.pdf", "faktura.isdoc") == "/doklady?filtr=kontrola"
    page = ready.get("/doklady?filtr=kontrola").text
    assert page.count("ke kontrole</span>") == 2
    resp = ready.post(
        "/doklady/nahrat",
        data={"csrf_token": token(ready)},
        files=[("soubory", ("virus.exe", b"MZ\x90\x00", "application/octet-stream"))],
    )
    assert resp.status_code == 400
    assert "virus.exe: Nepodporovaný typ souboru" in resp.text


def test_queue_moves_to_next_document(ready: TestClient) -> None:
    upload(ready, "faktura-radky.pdf", "faktura-sloupce.pdf")
    resp = ready.post(f"/doklady/PD{TODAY.year}-001", data=confirm_data(ready))
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/doklady/PD{TODAY.year}-002?potvrzeno=PD{TODAY.year}-001"


def test_confirm_errors_keep_values(ready: TestClient) -> None:
    location = upload(ready, "sken.pdf")
    resp = ready.post(location, data=confirm_data(ready, castka="abc", dodavatel_nazev=""))
    assert resp.status_code == 400
    assert "Částka není platné číslo" in resp.text
    assert 'value="2027000123"' in resp.text


def test_pay_later_and_undo(ready: TestClient) -> None:
    location = upload(ready, "faktura-radky.pdf")
    doc_id = location.rsplit("/", 1)[1]
    ready.post(location, data=confirm_data(ready))
    assert "Nezaplacené" in ready.get("/").text
    resp = ready.post(
        f"/doklady/{doc_id}/uhradit",
        data={
            "csrf_token": token(ready),
            "datum_uhrady": TODAY.isoformat(),
            "zpusob_uhrady": "hotovost",
        },
    )
    assert resp.status_code == 303
    journal = ready.get("/denik").text
    assert "V1" in journal
    ready.post(f"/doklady/{doc_id}/neuhrazeno", data={"csrf_token": token(ready)})
    assert doc_id not in ready.get("/denik").text


def test_discard_from_queue(ready: TestClient) -> None:
    location = upload(ready, "uctenka-qr.png")
    doc_id = location.rsplit("/", 1)[1]
    assert ready.get(f"/doklady/{doc_id}/nahled.png").content.startswith(b"\x89PNG")
    resp = ready.post(f"/doklady/{doc_id}/smazat", data={"csrf_token": token(ready)})
    assert resp.status_code == 303
    assert ready.get(location).status_code == 404


def test_manual_document(ready: TestClient) -> None:
    resp = ready.post(
        "/doklady/novy",
        data=confirm_data(
            ready,
            dodavatel_ico="",
            dodavatel_nazev="Trafika u nádraží",
            castka="89",
            typ="účtenka",
            kategorie="19",
            zpusob_uhrady="hotovost",
            uhrazeno="1",
        ),
    )
    assert resp.status_code == 303
    page = ready.get(resp.headers["location"]).text
    assert "Trafika u nádraží" in page and "uhrazen" in page
    assert "V1" in ready.get("/denik").text


def test_supplier_from_ares(ready: TestClient, fake_ares: FakeAres) -> None:
    resp = ready.get("/doklady/ares", params={"dodavatel_ico": "00006947"})
    assert "Ministerstvo financí" in resp.text and "ověřen" in resp.text
    assert "kontrolní" in ready.get("/doklady/ares", params={"dodavatel_ico": "12345678"}).text


def test_dhm_hint(ready: TestClient) -> None:
    resp = ready.post("/doklady/novy", data=confirm_data(ready, castka="95000", kategorie="19"))
    page = ready.get(resp.headers["location"]).text
    assert "nad 80 000 Kč" in page


def test_job_costs_and_material_warning(ready: TestClient) -> None:
    cid = new_contact(ready)
    jid = new_job(ready, cid)
    issue(ready, cid, jid, datum_vystaveni=(TODAY - timedelta(days=2)).isoformat())
    ready.post("/doklady/novy", data=confirm_data(ready, zakazka_id=jid, castka="600"))
    page = ready.get(f"/zakazky/{jid}").text
    assert "Přímé náklady" in page and "600,00" in page
    assert "3\xa0500,00" in page  # 4 100 invoiced - 600 costs
    assert "nakoupený po poslední faktuře" in page


# -- cash book ------------------------------------------------------------------------


def test_invoice_payment_lands_in_cash_book(ready: TestClient) -> None:
    cid = new_contact(ready)
    cislo = issue(ready, cid)
    ready.post(
        f"/faktury/{cislo}/uhrazena",
        data={
            "csrf_token": token(ready),
            "datum_uhrady": TODAY.isoformat(),
            "zpusob_uhrady": "hotovost",
        },
    )
    journal = ready.get("/denik").text
    assert f"Úhrada faktury {cislo}" in journal
    assert "5\xa0100,00" in journal  # cash 1 000 + 4 100
    assert "V deníku" in ready.get(f"/faktury/{cislo}").text


def test_manual_entry_transfer_and_delete(ready: TestClient) -> None:
    resp = ready.post(
        "/denik/novy",
        data={
            "csrf_token": token(ready),
            "smer": "výdaj",
            "ucet": "banka",
            "datum": TODAY.isoformat(),
            "castka": "3 000",
            "kategorie": "21",
            "popis": "Záloha sociální pojištění",
            "zpusob_uhrady": "převod",
            "zakazka_id": "",
            "poznamka": "",
        },
    )
    assert resp.status_code == 303
    resp = ready.post(
        "/denik/prevod",
        data={
            "csrf_token": token(ready),
            "smer": "do-pokladny",
            "datum": TODAY.isoformat(),
            "castka": "500",
            "popis": "",
        },
    )
    assert resp.status_code == 303
    page = ready.get("/denik").text
    assert "Záloha sociální pojištění" in page and "Výběr z účtu do pokladny" in page
    assert "1\xa0500,00" in page  # cash 1 000 + 500
    assert "46\xa0500,00" in page  # bank 50 000 - 3 000 - 500
    et = ready.get("/denik/et328").text
    assert "Kontrolní součty sedí" in et and "převedeno" in et
    entry_id = f"D{TODAY.year}-0001"
    ready.post(f"/denik/{entry_id}/smazat", data={"csrf_token": token(ready)})
    assert "Záloha sociální pojištění" not in ready.get("/denik").text


def test_manual_entry_validation(ready: TestClient) -> None:
    resp = ready.post(
        "/denik/novy",
        data={
            "csrf_token": token(ready),
            "smer": "příjem",
            "ucet": "banka",
            "datum": TODAY.isoformat(),
            "castka": "10",
            "kategorie": "15",
            "popis": "x",
            "zpusob_uhrady": "převod",
        },
    )
    assert resp.status_code == 400 and "Kategorie" in resp.text
    resp = ready.post(
        "/denik/novy",
        data={
            "csrf_token": token(ready),
            "smer": "příjem",
            "ucet": "banka",
            "datum": "2025-01-01",
            "castka": "10",
            "kategorie": "9",
            "popis": "x",
            "zpusob_uhrady": "převod",
        },
    )
    assert resp.status_code == 400 and "začíná" in resp.text


def test_cash_book_not_set_up(client: TestClient) -> None:
    complete_wizard(client)
    import tomllib

    settings = client.app.state.settings  # type: ignore[attr-defined]
    text = settings.firma_path.read_text("utf-8").replace('zacatek = "2026-01-01"', 'zacatek = ""')
    settings.firma_path.write_text(text, "utf-8")
    assert tomllib.loads(text)["evidence"]["zacatek"] == ""
    assert "Nastavit začátek evidence" in client.get("/denik").text
    assert "Nastavte začátek evidence" in client.get("/").text


def test_evidence_settings_validation(ready: TestClient) -> None:
    ready.post(
        "/denik/novy",
        data={
            "csrf_token": token(ready),
            "smer": "příjem",
            "ucet": "hotovost",
            "datum": "2026-03-01",
            "castka": "10",
            "kategorie": "9",
            "popis": "Tržba",
            "zpusob_uhrady": "převod",
        },
    )
    resp = ready.post(
        "/pruvodce/evidence",
        data={"csrf_token": token(ready), "zacatek": "2026-06-01", "hotovost": "-5", "banka": "x"},
    )
    assert resp.status_code == 400
    for msg in ("nemůže být později", "nesmí být záporný", "není platná částka"):
        assert msg in resp.text
    resp = ready.post(
        "/pruvodce/evidence",
        data={"csrf_token": token(ready), "zacatek": "2026-01-01", "hotovost": "200", "banka": "0"},
    )
    assert resp.headers["location"] == "/nastaveni?ulozeno=1"
