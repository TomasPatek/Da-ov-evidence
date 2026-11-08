"""Phase 4 scenarios on desktop and iPhone: assets, annual overview, locked year, bad upload."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_fakturace import login

pytestmark = pytest.mark.e2e
YEAR = date.today().year


def test_asset_and_annual_overview(page: Page, demo_url: str) -> None:
    login(page, demo_url)
    page.goto(demo_url + "/majetek/novy")
    page.fill("input[name=nazev]", "Diagnostický přístroj")
    page.fill("input[name=vstupni_cena]", "120000")
    page.select_option("select[name=odpisova_skupina]", "1")
    page.get_by_role("button", name="Založit kartu").click()
    expect(page.get_by_role("heading", name=re.compile("Diagnostický přístroj"))).to_be_visible()
    expect(page.locator("table.list")).to_contain_text("24 000,00 Kč")  # 20 % in year one
    page.goto(f"{demo_url}/prehledy?rok={YEAR}")
    expect(page.get_by_text("Daňové odpisy majetku")).to_be_visible()
    expect(page.locator(".report")).to_contain_text("24 000,00 Kč")
    with page.expect_download() as dl:
        page.get_by_role("link", name="PDF").click()
    assert dl.value.suggested_filename == f"prehled-{YEAR}.pdf"


def test_locked_year_cannot_be_changed(page: Page, demo_url: str) -> None:
    login(page, demo_url)
    page.goto(demo_url + "/nastaveni#zamek")
    page.fill("input[name=rok][type=number]", str(YEAR))
    page.get_by_role("button", name="Uzamknout").click()
    expect(page.get_by_text(f"Rok {YEAR} je uzamčený.")).to_be_visible()
    page.goto(demo_url + "/denik/novy")
    page.fill("input[name=castka]", "100")
    page.select_option("select[name=kategorie]", "19")
    page.fill("input[name=popis]", "Pokus o změnu")
    page.get_by_role("button", name="Zapsat").click()
    expect(
        page.get_by_text(re.compile(f"Rok {YEAR} je uzamčený a jeho záznamy nejde měnit"))
    ).to_be_visible()


def test_upload_of_forbidden_file_type_is_refused(
    page: Page, demo_url: str, tmp_path: Path
) -> None:
    login(page, demo_url)
    bad = tmp_path / "faktura.pdf.exe"
    bad.write_bytes(b"MZ\x90\x00 not a document")
    page.goto(demo_url + "/doklady")
    page.locator("section.upload input[name=soubory]").set_input_files(str(bad))
    page.get_by_role("button", name="Nahrát a přečíst").click()
    expect(page.get_by_role("alert")).to_contain_text("Nepodporovaný typ souboru")
