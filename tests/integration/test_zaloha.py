"""Backup page."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import complete_wizard, get_csrf


def test_backup_page_without_configuration(client: TestClient) -> None:
    complete_wizard(client)
    page = client.get("/zaloha").text
    assert "Záloha není nastavená" in page and "BACKUP_REPOSITORY" in page
    resp = client.post("/zaloha/spustit", data={"csrf_token": get_csrf(client, "/zaloha")})
    assert resp.headers["location"] == "/zaloha?bezi=1"
    assert "/zaloha" in client.get("/nastaveni").text
