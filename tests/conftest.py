from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ares.client import AresSubjekt, AresUnavailable
from app.config import Settings
from app.main import create_app

PASSWORD = "spravne-kone-baterie"
SETUP_TOKEN = "TESTKOD1"


class FakeAres:
    """In-memory ARES replacement."""

    def __init__(self) -> None:
        self.subjects: dict[str, AresSubjekt] = {
            "00006947": AresSubjekt(
                ico="00006947",
                nazev="Ministerstvo financí",
                dic="CZ00006947",
                ulice="Letenská 525/15",
                mesto="Praha 1",
                psc="11800",
                datum_aktualizace=None,
            )
        }
        self.down = False

    def lookup(self, ico: str) -> AresSubjekt | None:
        if self.down:
            raise AresUnavailable("down")
        return self.subjects.get(ico.zfill(8))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        secret_key="test-secret-key",
        cookie_secure=False,
        setup_token=SETUP_TOKEN,
    )


@pytest.fixture
def fake_ares() -> FakeAres:
    return FakeAres()


@pytest.fixture
def client(settings: Settings, fake_ares: FakeAres) -> Iterator[TestClient]:
    app = create_app(settings, ares=fake_ares)
    with TestClient(app, follow_redirects=False) as c:
        yield c


def csrf_from(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "CSRF token not found in page"
    return m.group(1)


def get_csrf(client: TestClient, path: str) -> str:
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.status_code)
    return csrf_from(resp.text)


def set_password(client: TestClient) -> None:
    token = get_csrf(client, "/pruvodce/heslo")
    resp = client.post(
        "/pruvodce/heslo",
        data={"csrf_token": token, "kod": SETUP_TOKEN, "heslo": PASSWORD, "heslo2": PASSWORD},
    )
    assert resp.status_code == 303, resp.text


PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f80f0000010101005d0a2db40000000049454e44ae426082"
)


def complete_wizard(client: TestClient) -> None:
    set_password(client)
    token = get_csrf(client, "/pruvodce/firma")
    steps: list[tuple[str, dict[str, str]]] = [
        (
            "/pruvodce/firma",
            {
                "nazev": "Jan Testovací",
                "ico": "00006947",
                "dic": "",
                "ulice": "Testovací 1",
                "mesto": "Praha 1",
                "psc": "11800",
                "email": "jan@example.cz",
                "telefon": "",
                "web": "",
                "zapis_rejstrik": "Zapsán v živnostenském rejstříku.",
            },
        ),
        ("/pruvodce/banka", {"ucet": "19-2000145399/0800"}),
        ("/pruvodce/posta", {}),
        ("/pruvodce/vzhled", {"primary": "#112233", "accent": "#ffcc00"}),
        (
            "/pruvodce/rada",
            {"format_cisla": "RRRRNNNN", "pocatecni_cislo": "1", "splatnost_dni": "14"},
        ),
    ]
    for path, data in steps:
        resp = client.post(path, data={"csrf_token": token, **data})
        assert resp.status_code == 303, (path, resp.text)
