"""Photo of a cash document through the web UI: invoice paid in cash, manual entry, cash book."""

from __future__ import annotations

import io
import re
from datetime import date

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests.conftest import complete_wizard, get_csrf
from tests.integration.test_fakturace import issue, new_contact

TODAY = date.today()


def photo() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), "white").save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def ready(client: TestClient) -> TestClient:
    complete_wizard(client)  # cash book starts 1. 1. 2026
    return client


def token(client: TestClient) -> str:
    return get_csrf(client, "/nastaveni")


def entry_id_in(page: str) -> str:
    m = re.search(r"/denik/(D\d{4}-\d{4})/priloha", page)
    assert m, "no attachment form or link on the page"
    return m.group(1)


def test_invoice_paid_in_cash_with_photo(ready: TestClient) -> None:
    cislo = issue(ready, new_contact(ready))
    resp = ready.post(
        f"/faktury/{cislo}/uhrazena",
        data={
            "csrf_token": token(ready),
            "datum_uhrady": TODAY.isoformat(),
            "zpusob_uhrady": "hotovost",
        },
        files={"priloha": ("IMG_0042.JPG", photo(), "image/jpeg")},
    )
    assert resp.status_code == 303, resp.text
    page = ready.get(f"/faktury/{cislo}").text
    assert "📎 Doklad PPD1/" in page
    entry_id = entry_id_in(page)
    image = ready.get(f"/denik/{entry_id}/priloha")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"
    assert image.headers["x-content-type-options"] == "nosniff"
    assert "📎 Doklad<" in ready.get(f"/denik?rok={TODAY.year}").text


def test_photo_added_later_and_removed(ready: TestClient) -> None:
    cislo = issue(ready, new_contact(ready))
    ready.post(
        f"/faktury/{cislo}/uhrazena",
        data={
            "csrf_token": token(ready),
            "datum_uhrady": TODAY.isoformat(),
            "zpusob_uhrady": "hotovost",
        },
    )
    page = ready.get(f"/faktury/{cislo}").text
    assert "Přidat fotku dokladu" in page
    entry_id = entry_id_in(page)
    resp = ready.post(
        f"/denik/{entry_id}/priloha",
        data={"csrf_token": token(ready), "zpet": f"/faktury/{cislo}"},
        files={"priloha": ("sken.pdf", b"%PDF-1.4\n", "application/pdf")},
    )
    assert resp.status_code == 303 and resp.headers["location"] == f"/faktury/{cislo}"
    pdf = ready.get(f"/denik/{entry_id}/priloha")
    assert pdf.headers["content-disposition"].startswith("attachment")
    resp = ready.post(
        f"/denik/{entry_id}/priloha/smazat",
        data={"csrf_token": token(ready), "zpet": "https://example.com/"},
    )
    assert resp.headers["location"] == f"/denik?rok={TODAY.year}"  # never another site
    assert ready.get(f"/denik/{entry_id}/priloha").status_code == 404


def test_manual_cash_entry_with_photo(ready: TestClient) -> None:
    resp = ready.post(
        "/denik/novy",
        data={
            "csrf_token": token(ready),
            "smer": "výdaj",
            "ucet": "hotovost",
            "datum": TODAY.isoformat(),
            "kategorie": "16",
            "castka": "120",
            "popis": "Drobný materiál",
        },
        files={"priloha": ("uctenka.jpg", photo(), "image/jpeg")},
    )
    assert resp.status_code == 303, resp.text
    page = ready.get(f"/denik?rok={TODAY.year}").text
    assert "📎 Doklad<" in page and "VPD1/" in page


def test_wrong_file_is_refused_and_nothing_is_written(ready: TestClient) -> None:
    resp = ready.post(
        "/denik/novy",
        data={
            "csrf_token": token(ready),
            "smer": "výdaj",
            "ucet": "hotovost",
            "datum": TODAY.isoformat(),
            "kategorie": "16",
            "castka": "120",
            "popis": "Drobný materiál",
        },
        files={"priloha": ("virus.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert "PDF nebo fotku" in resp.text
    assert "Drobný materiál" not in ready.get(f"/denik?rok={TODAY.year}").text


def test_attachment_of_unknown_entry(ready: TestClient) -> None:
    assert ready.get("/denik/D2026-0999/priloha").status_code == 404
    assert ready.get("/denik/..%2F..%2Fconfig/priloha").status_code == 404


def test_correct_cash_voucher_number(ready: TestClient) -> None:
    cislo = issue(ready, new_contact(ready))
    ready.post(
        f"/faktury/{cislo}/uhrazena",
        data={
            "csrf_token": token(ready),
            "datum_uhrady": TODAY.isoformat(),
            "zpusob_uhrady": "hotovost",
        },
    )
    page = ready.get(f"/faktury/{cislo}").text
    assert "Opravit číslo" in page
    entry_id = entry_id_in(page)
    yy = f"{TODAY.year % 100:02d}"
    resp = ready.post(
        f"/denik/{entry_id}/cislo",
        data={"csrf_token": token(ready), "cislo": "4", "zpet": f"/faktury/{cislo}"},
    )
    assert resp.status_code == 303 and resp.headers["location"] == f"/faktury/{cislo}"
    assert f"PPD4/{yy}" in ready.get(f"/faktury/{cislo}").text
    assert f"PPD4/{yy}" in ready.get(f"/denik?rok={TODAY.year}").text
    resp = ready.post(
        f"/denik/{entry_id}/cislo", data={"csrf_token": token(ready), "cislo": f"VPD4/{yy}"}
    )
    assert resp.status_code == 400 and "Příjem do pokladny má číslo PPD" in resp.text
