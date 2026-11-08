"""Phase 2 scenario on desktop and iPhone: upload ISDOC, review, assign job, cash book."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_fakturace import login

pytestmark = pytest.mark.e2e
FIXTURES = Path(__file__).parents[1] / "fixtures" / "doklady"


def test_upload_review_and_job_profit(page: Page, demo_url: str) -> None:
    login(page, demo_url)
    page.goto(demo_url + "/doklady")
    page.set_input_files("input[name=soubory]", str(FIXTURES / "faktura-radky.pdf"))
    page.get_by_role("button", name="Nahrát a přečíst").click()

    # Review form with preview and pre-filled fields.
    expect(page).to_have_url(re.compile(r"/doklady/PD\d{4}-\d{3}$"))
    expect(page.locator(".preview img").first).to_be_visible()
    expect(page.locator("input[name=castka]")).to_have_value("1500,00")
    expect(page.locator("label.uncertain").first).to_be_visible()
    page.select_option("select[name=kategorie]", "15")
    job = page.locator(
        "select[name=zakazka_id] option", has_text="Rekonstrukce koupelny"
    ).get_attribute("value")
    page.select_option("select[name=zakazka_id]", job)
    page.check("input[name=uhrazeno]")
    page.get_by_role("button", name="Potvrdit").click()

    # The queue continues with the next waiting document.
    expect(page.get_by_text(re.compile(r"Doklad PD\d{4}-\d{3} potvrzen"))).to_be_visible()

    page.goto(f"{demo_url}/zakazky/{job}")
    expect(page.get_by_text("Přímé náklady")).to_be_visible()
    costs = page.locator(".card").filter(
        has=page.get_by_role("heading", name="Náklady", exact=True)
    )
    expect(costs).to_contain_text("Díly Vzor s.r.o.")

    page.goto(demo_url + "/denik")
    expect(page.locator("table.list")).to_contain_text("Díly Vzor s.r.o.")


def test_cash_book_entry_and_et328(page: Page, demo_url: str) -> None:
    login(page, demo_url)
    page.goto(demo_url + "/denik/novy")
    page.check("input[name=smer][value=příjem]")
    page.check("input[name=ucet][value=hotovost]")
    page.fill("input[name=castka]", "1200")
    page.select_option("select[name=kategorie]", "9")
    page.fill("input[name=popis]", "Tržba za opravu pračky")
    page.get_by_role("button", name="Zapsat").click()
    expect(page.get_by_text("Zapsáno.")).to_be_visible()
    expect(page.locator("table.list")).to_contain_text("Tržba za opravu pračky")
    page.get_by_role("link", name="Tabulka ET 328").click()
    expect(page.get_by_text("Kontrolní součty sedí.")).to_be_visible()
    expect(page.locator("table.et")).to_contain_text("převedeno")


def test_manual_document(page: Page, demo_url: str) -> None:
    login(page, demo_url)
    page.goto(demo_url + "/doklady")
    page.get_by_role("link", name="Zadat ručně").click()
    expect(page.get_by_role("heading", name="Ruční zadání dokladu")).to_be_visible()
    page.check("input[name=typ][value=účtenka]")
    page.fill("input[name=dodavatel_nazev]", "Železářství U Kováře")
    page.fill("input[name=castka]", "245,50")
    page.select_option("select[name=kategorie]", "19")
    page.select_option("select[name=zpusob_uhrady]", "hotovost")
    page.check("input[name=uhrazeno]")
    page.get_by_role("button", name="Uložit doklad").click()
    expect(page.get_by_text("Uloženo.")).to_be_visible()
    page.goto(demo_url + "/denik")
    expect(page.locator("table.list")).to_contain_text("Železářství U Kováře")
    expect(page.locator("table.list")).to_contain_text("VPD1/")
