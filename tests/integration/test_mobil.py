"""Phone: receipt photo upload through HTMX, home screen icon and manifest."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image

from tests.conftest import complete_wizard, get_csrf


def test_manifest_and_icons_are_public(client: TestClient) -> None:
    resp = client.get("/static/manifest.webmanifest")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/manifest+json")
    assert resp.json()["display"] == "standalone"
    for path in (
        "/static/icons/apple-touch-icon.png",
        "/static/icons/icon-512.png",
        "/favicon.ico",
    ):
        assert client.get(path).content.startswith(b"\x89PNG")


def test_pages_link_manifest(client: TestClient) -> None:
    complete_wizard(client)
    page = client.get("/").text
    assert 'rel="manifest"' in page and 'rel="apple-touch-icon"' in page
    assert "Vyfotit účtenku" in page


def test_photo_upload_by_htmx(client: TestClient) -> None:
    complete_wizard(client)
    token = get_csrf(client, "/doklady")
    assert 'capture="environment"' in client.get("/doklady").text
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), "white").save(buf, format="JPEG")
    resp = client.post(
        "/doklady/nahrat",
        data={"csrf_token": token, "zdroj": "foto"},
        files=[("soubory", ("IMG_0001.JPG", buf.getvalue(), "image/jpeg"))],
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 204
    target = resp.headers["HX-Redirect"]
    page = client.get(target).text
    assert "ke kontrole" in page
    assert client.get(target + "/nahled.png").content.startswith(b"\x89PNG")
    (doc,) = [
        d
        for d in client.app.state.storage.table(  # type: ignore[attr-defined]
            __import__("app.received", fromlist=["DOKLADY_SCHEMA"]).DOKLADY_SCHEMA,
            int(target.split("PD")[1][:4]),
        ).all()
    ]
    assert doc["zdroj"] == "foto"
