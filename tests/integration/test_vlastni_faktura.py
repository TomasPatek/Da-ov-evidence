"""An invoice issued in Air Bank uploaded (or e-mailed) and taken over through the UI."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import complete_wizard, get_csrf

FIXTURE = Path(__file__).parents[1] / "fixtures" / "doklady" / "vydana-airbank.pdf"
AIRBANK = Path(__file__).parents[1] / "fixtures" / "airbank"


def token(client: TestClient) -> str:
    return get_csrf(client, "/nastaveni")


@pytest.fixture
def ready(client: TestClient) -> TestClient:
    complete_wizard(client)
    # The fixture is issued by the demo company with this IČO and account.
    resp = client.post(
        "/pruvodce/firma",
        data={
            "csrf_token": token(client),
            "nazev": "Jana Vzorová",
            "ico": "99999994",
            "dic": "",
            "ulice": "Ukázková 12",
            "mesto": "Horní Dolní",
            "psc": "54321",
            "email": "",
            "telefon": "",
            "web": "",
            "zapis_rejstrik": "",
        },
    )
    assert resp.status_code == 303
    client.post("/pruvodce/banka", data={"csrf_token": token(client), "ucet": "1000000005/3030"})
    return client


def upload(client: TestClient) -> str:
    resp = client.post(
        "/doklady/nahrat",
        data={"csrf_token": token(client)},
        files=[("soubory", ("faktura.pdf", FIXTURE.read_bytes(), "application/pdf"))],
    )
    assert resp.status_code == 303
    return resp.headers["location"]


def take_over_data(client: TestClient, **kw: str) -> dict[str, str]:
    data = {
        "csrf_token": token(client),
        "cislo": "20260042",
        "vs": "20260042",
        "kontakt_id": "",
        "nazev": "Petr Zákazník",
        "ulice": "Lipová 3",
        "psc": "54321",
        "mesto": "Vzorov",
        "ico": "",
        "datum_vystaveni": "2026-11-05",
        "datum_splatnosti": "2026-11-19",
        "castka": "1 250,00",
        "popis": "Oprava pračky",
        "zakazka_id": "",
    }
    data.update(kw)
    return data


def test_take_over_flow(ready: TestClient) -> None:
    location = upload(ready)
    page = ready.get(location).text
    assert "Vaše vydaná faktura 20260042" in page
    assert 'value="Petr Zákazník"' in page and 'value="1250,00"' in page
    assert "vaše faktura" in ready.get("/doklady?filtr=kontrola").text
    doc_id = location.rsplit("/", 1)[1]
    resp = ready.post(f"/doklady/{doc_id}/prevzit", data=take_over_data(ready))
    assert resp.headers["location"] == "/faktury/20260042?prevzato=1"
    detail = ready.get("/faktury/20260042?prevzato=1").text
    assert "převzatá z Air Bank" in detail and "/faktury/20260042/upravit" not in detail
    assert ready.get("/faktury/20260042/upravit").status_code == 400
    assert ready.get("/faktury/20260042/pdf").content == FIXTURE.read_bytes()
    assert ready.get(location).status_code == 404  # gone from the queue


def test_payment_waiting_in_bank_is_matched_on_take_over(ready: TestClient) -> None:
    data = (AIRBANK / "prichozi-uhrada.eml").read_bytes()
    data = data.replace(b"20260001", b"20260042").replace(b"4 100,00", b"1 250,00")
    ready.post(
        "/banka/nahrat",
        data={"csrf_token": token(ready)},
        files=[("soubory", ("n.eml", data, "message/rfc822"))],
    )
    location = upload(ready)
    ready.post(f"{location}/prevzit", data=take_over_data(ready))
    assert "uhrazena" in ready.get("/faktury/20260042").text


def test_take_over_errors(ready: TestClient) -> None:
    location = upload(ready)
    resp = ready.post(f"{location}/prevzit", data=take_over_data(ready, castka="x", popis=""))
    assert resp.status_code == 400
    assert "Částka není platné číslo" in resp.text and "Vyplňte, co fakturujete" in resp.text
    resp = ready.post(f"{location}/prevzit", data=take_over_data(ready, cislo="AB-1"))
    assert resp.status_code == 400 and "číselné řadě" in resp.text
