"""Phase 4 through the web UI: assets, annual overview with exports, year lock."""

from __future__ import annotations

import io
from datetime import date

import pdfplumber
import pytest
from fastapi.testclient import TestClient

from tests.conftest import complete_wizard, get_csrf

YEAR = date.today().year


def token(client: TestClient) -> str:
    return get_csrf(client, "/nastaveni")


@pytest.fixture
def ready(client: TestClient) -> TestClient:
    complete_wizard(client)  # cash book from 1. 1. 2026
    return client


def add_asset(client: TestClient, **kw: str) -> str:
    data = {
        "csrf_token": token(client),
        "nazev": "Dodávka",
        "datum_porizeni": f"{YEAR}-03-01",
        "vstupni_cena": "300 000",
        "odpisova_skupina": "2",
        "zpusob_odpisu": "rovnoměrný",
        "doklad_id": "",
        "poznamka": "",
    }
    data.update(kw)
    resp = client.post("/majetek/novy", data=data)
    assert resp.status_code == 303, resp.text
    return resp.headers["location"].rsplit("/", 1)[1]


def test_asset_lifecycle(ready: TestClient) -> None:
    aid = add_asset(ready)
    page = ready.get(f"/majetek/{aid}").text
    assert "33\xa0000,00" in page and "66\xa0750,00" in page  # 11 %, then 22,25 %
    ready.post(f"/majetek/{aid}/prerusit/{YEAR + 1}", data={"csrf_token": token(ready)})
    assert "Obnovit odpisování" in ready.get(f"/majetek/{aid}").text
    ready.post(
        f"/majetek/{aid}/vyradit",
        data={"csrf_token": token(ready), "datum_vyrazeni": f"{YEAR + 3}-06-30"},
    )
    assert "vyřazení (½)" in ready.get(f"/majetek/{aid}").text
    assert "Dodávka" in ready.get("/majetek").text


def test_asset_validation(ready: TestClient) -> None:
    resp = ready.post(
        "/majetek/novy",
        data={
            "csrf_token": token(ready),
            "nazev": "",
            "datum_porizeni": f"{YEAR}-01-01",
            "vstupni_cena": "50000",
            "odpisova_skupina": "9",
            "zpusob_odpisu": "rychle",
        },
    )
    assert resp.status_code == 400
    for msg in ("Vyplňte název", "nad 80 000", "skupinu", "způsob"):
        assert msg in resp.text


def test_annual_overview_and_exports(ready: TestClient) -> None:
    ready.post(
        "/denik/novy",
        data={
            "csrf_token": token(ready),
            "smer": "příjem",
            "ucet": "banka",
            "datum": f"{YEAR}-01-15",
            "castka": "100 000",
            "kategorie": "9",
            "popis": "Tržby",
            "zpusob_uhrady": "převod",
        },
    )
    add_asset(ready)
    page = ready.get(f"/prehledy?rok={YEAR}").text
    assert "Dílčí základ daně" in page and "67\xa0000,00" in page  # 100 000 − 33 000
    md = ready.get(f"/prehledy/{YEAR}.md")
    assert "attachment" in md.headers["content-disposition"]
    assert "| Dílčí základ daně (§ 7) | 67 000,00 Kč |" in md.text
    pdf = ready.get(f"/prehledy/{YEAR}.pdf")
    with pdfplumber.open(io.BytesIO(pdf.content)) as doc:
        text = doc.pages[0].extract_text().replace("\xa0", " ")
    assert f"Roční přehled {YEAR}" in text and "67 000,00 Kč" in text


def test_locked_year_in_ui(ready: TestClient) -> None:
    ready.post("/nastaveni/zamek", data={"csrf_token": token(ready), "rok": str(YEAR)})
    assert f"Rok {YEAR} je uzamčený." in ready.get("/nastaveni").text
    resp = ready.post(
        "/denik/novy",
        data={
            "csrf_token": token(ready),
            "smer": "výdaj",
            "ucet": "banka",
            "datum": f"{YEAR}-02-01",
            "castka": "10",
            "kategorie": "19",
            "popis": "Poplatek",
            "zpusob_uhrady": "převod",
        },
    )
    assert resp.status_code == 409 and "je uzamčený" in resp.text
    # Wrong confirmation keeps it locked, the right one unlocks.
    ready.post(
        "/nastaveni/zamek",
        data={"csrf_token": token(ready), "rok": str(YEAR), "akce": "odemknout", "potvrzeni": "x"},
    )
    assert f"Rok {YEAR} je uzamčený." in ready.get("/nastaveni").text
    ready.post(
        "/nastaveni/zamek",
        data={
            "csrf_token": token(ready),
            "rok": str(YEAR),
            "akce": "odemknout",
            "potvrzeni": str(YEAR),
        },
    )
    assert f"Rok {YEAR} je uzamčený." not in ready.get("/nastaveni").text
