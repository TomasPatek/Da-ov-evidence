from __future__ import annotations

import tomllib

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import (
    PASSWORD,
    PNG_1PX,
    SETUP_TOKEN,
    FakeAres,
    complete_wizard,
    csrf_from,
    get_csrf,
    set_password,
)

PROTECTED = ["/", "/nastaveni", "/pruvodce/firma", "/pruvodce/banka", "/pruvodce/rada"]


def logout(client: TestClient) -> None:
    token = get_csrf(client, "/nastaveni")
    assert client.post("/odhlaseni", data={"csrf_token": token}).status_code == 303


def test_health_is_public(client: TestClient) -> None:
    assert client.get("/zdravi").json() == {"stav": "ok"}


@pytest.mark.parametrize("path", [*PROTECTED, "/prihlaseni"])
def test_before_setup_everything_leads_to_password_step(client: TestClient, path: str) -> None:
    resp = client.get(path)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/pruvodce/heslo"


def test_password_step_requires_setup_code(client: TestClient) -> None:
    token = get_csrf(client, "/pruvodce/heslo")
    resp = client.post(
        "/pruvodce/heslo",
        data={"csrf_token": token, "kod": "SPATNE", "heslo": PASSWORD, "heslo2": PASSWORD},
    )
    assert resp.status_code == 400
    assert "Nesprávný kód" in resp.text
    assert not client.app.state.passwords.is_set()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("heslo", "heslo2", "message"),
    [("kratke", "kratke", "alespoň 12"), (PASSWORD, PASSWORD + "x", "neshodují")],
)
def test_password_validation(client: TestClient, heslo: str, heslo2: str, message: str) -> None:
    token = get_csrf(client, "/pruvodce/heslo")
    resp = client.post(
        "/pruvodce/heslo",
        data={"csrf_token": token, "kod": SETUP_TOKEN, "heslo": heslo, "heslo2": heslo2},
    )
    assert resp.status_code == 400
    assert message in resp.text


def test_password_step_closed_after_setup(client: TestClient) -> None:
    set_password(client)
    assert client.get("/pruvodce/heslo").headers["location"] == "/pruvodce"
    logout(client)
    # Not reachable anonymously any more either.
    assert client.get("/pruvodce/heslo").headers["location"].startswith("/prihlaseni")


def test_post_without_csrf_is_rejected(client: TestClient) -> None:
    client.get("/pruvodce/heslo")
    resp = client.post(
        "/pruvodce/heslo", data={"kod": SETUP_TOKEN, "heslo": PASSWORD, "heslo2": PASSWORD}
    )
    assert resp.status_code == 403
    resp = client.post(
        "/pruvodce/heslo",
        data={"csrf_token": "forged", "kod": SETUP_TOKEN, "heslo": PASSWORD, "heslo2": PASSWORD},
    )
    assert resp.status_code == 403


def test_csrf_header_is_accepted(client: TestClient) -> None:
    token = get_csrf(client, "/pruvodce/heslo")
    resp = client.post(
        "/pruvodce/heslo",
        data={"kod": SETUP_TOKEN, "heslo": PASSWORD, "heslo2": PASSWORD},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 303


@pytest.mark.parametrize("path", PROTECTED)
def test_anonymous_user_sees_no_page(client: TestClient, path: str) -> None:
    complete_wizard(client)
    logout(client)
    resp = client.get(path)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/prihlaseni?next=")


def test_htmx_request_gets_hx_redirect(client: TestClient) -> None:
    complete_wizard(client)
    logout(client)
    resp = client.get("/pruvodce/ares?ico=00006947", headers={"HX-Request": "true"})
    assert resp.status_code == 401
    assert resp.headers["hx-redirect"].startswith("/prihlaseni")


def test_login_logout_flow(client: TestClient) -> None:
    complete_wizard(client)
    logout(client)
    page = client.get("/prihlaseni?next=/nastaveni")
    token = csrf_from(page.text)
    bad = client.post("/prihlaseni", data={"csrf_token": token, "heslo": "spatne", "next": "/"})
    assert bad.status_code == 401
    ok = client.post(
        "/prihlaseni", data={"csrf_token": token, "heslo": PASSWORD, "next": "/nastaveni"}
    )
    assert ok.status_code == 303
    assert ok.headers["location"] == "/nastaveni"
    assert client.get("/nastaveni").status_code == 200


@pytest.mark.parametrize("target", ["//evil.example", "https://evil.example", "/\\evil"])
def test_login_does_not_redirect_offsite(client: TestClient, target: str) -> None:
    complete_wizard(client)
    logout(client)
    token = get_csrf(client, "/prihlaseni")
    resp = client.post("/prihlaseni", data={"csrf_token": token, "heslo": PASSWORD, "next": target})
    assert resp.headers["location"] == "/"


def test_login_session_is_renewed(client: TestClient) -> None:
    complete_wizard(client)
    logout(client)
    token = get_csrf(client, "/prihlaseni")
    client.post("/prihlaseni", data={"csrf_token": token, "heslo": PASSWORD, "next": "/"})
    # The pre-login CSRF token must not stay valid after login.
    assert csrf_from(client.get("/nastaveni").text) != token


def test_login_throttling(client: TestClient) -> None:
    complete_wizard(client)
    logout(client)
    token = get_csrf(client, "/prihlaseni")
    for _ in range(5):
        r = client.post("/prihlaseni", data={"csrf_token": token, "heslo": "spatne", "next": "/"})
        assert r.status_code == 401
    blocked = client.post("/prihlaseni", data={"csrf_token": token, "heslo": PASSWORD, "next": "/"})
    assert blocked.status_code == 429
    assert "Příliš mnoho" in blocked.text


def test_wizard_writes_configuration(client: TestClient, settings: Settings) -> None:
    complete_wizard(client)
    data = tomllib.loads(settings.firma_path.read_text(encoding="utf-8"))
    assert data["firma"]["nazev"] == "Jan Testovací"
    assert data["firma"]["ico"] == "00006947"
    assert data["banka"] == {"ucet": "19-2000145399/0800", "iban": "CZ6508000000192000145399"}
    assert data["fakturace"]["format_cisla"] == "RRRRNNNN"
    assert data["aplikace"]["pruvodce_dokoncen"] is True
    theme = (settings.branding_dir / "theme.css").read_text(encoding="utf-8")
    assert "--brand-primary: #112233;" in theme
    assert "--brand-primary-contrast: #ffffff;" in theme
    assert "--brand-accent-contrast: #000000;" in theme
    assert client.get("/branding/theme.css").text == theme
    dash = client.get("/")
    assert dash.status_code == 200
    assert "Jan Testovací" in dash.text


def test_dashboard_redirects_to_wizard_until_done(client: TestClient) -> None:
    set_password(client)
    assert client.get("/").headers["location"] == "/pruvodce"


def test_wizard_validation_errors(client: TestClient) -> None:
    set_password(client)
    token = get_csrf(client, "/pruvodce/firma")
    resp = client.post(
        "/pruvodce/firma", data={"csrf_token": token, "ico": "12345678", "psc": "1", "email": "x"}
    )
    assert resp.status_code == 400
    for msg in ("Vyplňte název", "kontrolní součet", "PSČ", "E-mail"):
        assert msg in resp.text
    resp = client.post("/pruvodce/banka", data={"csrf_token": token, "ucet": "124/0800"})
    assert resp.status_code == 400
    resp = client.post(
        "/pruvodce/rada",
        data={
            "csrf_token": token,
            "format_cisla": "RRRRNNN",
            "pocatecni_cislo": "1000",
            "splatnost_dni": "14",
        },
    )
    assert resp.status_code == 400
    assert "od 1 do 999" in resp.text


def test_ares_fragment(client: TestClient, fake_ares: FakeAres) -> None:
    set_password(client)
    resp = client.get("/pruvodce/ares?ico=6947", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert 'value="Ministerstvo financí"' in resp.text
    assert 'value="Letenská 525/15"' in resp.text
    assert "Údaje načteny z ARES" in resp.text

    assert "kontrolní součet" in client.get("/pruvodce/ares?ico=12345678").text
    assert "neexistuje" in client.get("/pruvodce/ares?ico=99999994").text
    fake_ares.down = True
    assert "nedostupný" in client.get("/pruvodce/ares?ico=00006947").text


def test_logo_upload(client: TestClient, settings: Settings) -> None:
    set_password(client)
    token = get_csrf(client, "/pruvodce/vzhled")

    def upload(name: str, data: bytes, ctype: str) -> int:
        resp = client.post(
            "/pruvodce/vzhled", data={"csrf_token": token}, files={"logo": (name, data, ctype)}
        )
        return resp.status_code

    assert upload("logo.png", PNG_1PX, "image/png") == 303
    assert (settings.branding_dir / "logo.png").exists()
    logo = client.get("/branding/logo")
    assert logo.headers["content-type"] == "image/png"
    assert "sandbox" in logo.headers["content-security-policy"]

    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>'
    assert upload("logo.svg", svg, "image/svg+xml") == 303
    assert (settings.branding_dir / "logo.svg").exists()
    assert not (settings.branding_dir / "logo.png").exists()

    evil = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    assert upload("evil.svg", evil, "image/svg+xml") == 400
    evil2 = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>'
    assert upload("evil.svg", evil2, "image/svg+xml") == 400
    assert upload("fake.png", b"GIF89a....", "image/png") == 400
    assert upload("big.png", PNG_1PX + b"\0" * (1024 * 1024), "image/png") == 400


def test_invalid_color_is_rejected(client: TestClient) -> None:
    set_password(client)
    token = get_csrf(client, "/pruvodce/vzhled")
    resp = client.post(
        "/pruvodce/vzhled", data={"csrf_token": token, "primary": "red;}body{x:y", "accent": ""}
    )
    assert resp.status_code == 400


def test_security_headers(client: TestClient) -> None:
    resp = client.get("/pruvodce/heslo")
    assert "default-src 'self'" in resp.headers["content-security-policy"]
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["cache-control"] == "no-store"


def test_session_cookie_flags(settings: Settings) -> None:
    secure = Settings(**{**settings.__dict__, "cookie_secure": True})
    app = create_app(secure, ares=FakeAres())
    with TestClient(app, base_url="https://testserver", follow_redirects=False) as c:
        resp = c.get("/pruvodce/heslo")
        cookie = resp.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=strict" in cookie
        assert "secure" in cookie


def test_setup_code_is_logged_when_generated(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    no_token = Settings(**{**settings.__dict__, "setup_token": None})
    with caplog.at_level("WARNING"):
        app = create_app(no_token, ares=FakeAres())
    assert app.state.setup_token in caplog.text
