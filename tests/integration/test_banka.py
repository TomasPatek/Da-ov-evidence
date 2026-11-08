"""Phase 3 through the web UI: bank movements, matching, mail status and manual fetch."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import FakeAres, FakeMailer, complete_wizard, get_csrf
from tests.integration.test_fakturace import issue, new_contact
from tests.unit.test_mail_fetch import FakeMailbox, doc_mail, other_mail

AIRBANK = Path(__file__).parents[1] / "fixtures" / "airbank"


def token(client: TestClient) -> str:
    return get_csrf(client, "/nastaveni")


def use_airbank_account(client: TestClient) -> None:
    resp = client.post(
        "/pruvodce/banka", data={"csrf_token": token(client), "ucet": "1000000005/3030"}
    )
    assert resp.status_code == 303


@pytest.fixture
def ready(client: TestClient) -> TestClient:
    complete_wizard(client)
    use_airbank_account(client)
    return client


@pytest.fixture
def mailbox() -> FakeMailbox:
    return FakeMailbox([])


@pytest.fixture
def mail_client(
    settings: Settings, fake_ares: FakeAres, fake_mailer: FakeMailer, mailbox: FakeMailbox
) -> Iterator[TestClient]:
    configured = replace(
        settings,
        imap_host="imap.example.cz",
        imap_user="fakturace@example.cz",
        imap_password="tajne",
        posta_interval_min=0,
    )
    app = create_app(
        configured, ares=fake_ares, mailer=fake_mailer, mailbox_factory=lambda: mailbox
    )
    with TestClient(app, follow_redirects=False) as c:
        complete_wizard(c)
        use_airbank_account(c)
        yield c


def upload_eml(client: TestClient, *names: str) -> str:
    files = [("soubory", (n, (AIRBANK / n).read_bytes(), "message/rfc822")) for n in names]
    resp = client.post("/banka/nahrat", data={"csrf_token": token(client)}, files=files)
    return resp.text


def test_pages_need_login(client: TestClient) -> None:
    complete_wizard(client)
    client.cookies.clear()
    for path in ("/banka", "/posta"):
        assert "/prihlaseni" in client.get(path).headers["location"]


def test_upload_notification_matches_invoice(ready: TestClient) -> None:
    cid = new_contact(ready)
    cislo = issue(ready, cid)  # 4 100 Kč
    # The sample carries VS 20260001; use the number this year's invoice got.
    data = (AIRBANK / "prichozi-uhrada.eml").read_bytes().replace(b"20260001", cislo.encode())
    resp = ready.post(
        "/banka/nahrat",
        data={"csrf_token": token(ready)},
        files=[("soubory", ("n.eml", data, "message/rfc822"))],
    )
    assert "automaticky spárováno: 1" in resp.text
    assert "uhrazena" in ready.get(f"/faktury/{cislo}").text
    assert "900000000004" in ready.get("/denik").text


def test_unmatched_movement_actions(ready: TestClient) -> None:
    upload_eml(ready, "odchozi-uhrada.eml", "vklad-bankomat.eml", "platba-cvakem.eml")
    page = ready.get("/banka").text
    assert 'Ke spárování <span class="badge">3</span>' in page
    ids = sorted(set(__import__("re").findall(r'id="(BP\d{4}-\d{4})"', page)))
    out, deposit, card = ids[0], ids[1], ids[2]
    # Write as another movement (social insurance), transfer and ignore.
    resp = ready.post(
        f"/banka/{out}/zapsat",
        data={"csrf_token": token(ready), "kategorie": "21", "popis": "Pojistné", "zakazka_id": ""},
    )
    assert resp.status_code == 303
    assert (
        ready.post(f"/banka/{deposit}/prevod", data={"csrf_token": token(ready)}).status_code == 303
    )
    resp = ready.post(f"/banka/{card}/ignorovat", data={"csrf_token": token(ready), "duvod": ""})
    assert resp.status_code == 400 and "důvod" in resp.text
    ready.post(f"/banka/{card}/ignorovat", data={"csrf_token": token(ready), "duvod": "duplicita"})
    assert "Vše je spárované" in ready.get("/banka").text
    journal = ready.get("/denik").text
    assert "Pojistné" in journal and "Vklad hotovosti na účet" in journal
    # Undo the transfer.
    ready.post(f"/banka/{deposit}/zrusit", data={"csrf_token": token(ready)})
    assert "Vklad hotovosti na účet" not in ready.get("/denik").text


def test_upload_rejects_other_mail(ready: TestClient) -> None:
    resp = ready.post(
        "/banka/nahrat",
        data={"csrf_token": token(ready)},
        files=[("soubory", ("x.eml", other_mail(), "message/rfc822"))],
    )
    assert resp.status_code == 400 and "není to notifikace" in resp.text


def test_mail_page_without_configuration(ready: TestClient) -> None:
    page = ready.get("/posta").text
    assert "není nastavené" in page and "IMAP_" in page


def test_manual_fetch(mail_client: TestClient, mailbox: FakeMailbox) -> None:
    mailbox.inbox.update(
        {"1": (AIRBANK / "platba-cvakem.eml").read_bytes(), "2": doc_mail(), "3": other_mail()}
    )
    page = mail_client.get("/posta").text
    assert "imap.example.cz" in page and "Pošta se zatím nestahovala" in page
    resp = mail_client.post("/posta/stahnout", data={"csrf_token": token(mail_client)})
    assert resp.headers["location"] == "/posta?hotovo=1"
    page = mail_client.get("/posta").text
    assert "1 (spárováno 0)" in page and "Doklady z příloh</dt><dd>1" in page
    assert set(mailbox.inbox) == {"3"}
    assert "Platby ke spárování: 1" in mail_client.get("/").text
