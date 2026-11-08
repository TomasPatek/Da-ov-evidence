"""Phase 1 main scenario on desktop and iPhone: contact from ARES, job, invoice, payment."""

from __future__ import annotations

import io
import re
from datetime import date

import pdfplumber
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

DEMO_PASSWORD = "demo-heslo-1234"


def login(page: Page, url: str) -> None:
    page.goto(url + "/prihlaseni")
    page.fill("input[name=heslo]", DEMO_PASSWORD)
    page.click("button[type=submit]")
    expect(page.get_by_role("heading", name="Přehled")).to_be_visible()


def test_contact_job_invoice_payment(page: Page, demo_url: str) -> None:
    login(page, demo_url)

    # 1. New contact via IČO (offline demo ARES).
    page.goto(demo_url + "/kontakty/novy")
    page.fill("input[name=ico]", "99990024")
    page.get_by_role("button", name="Načíst z ARES").click()
    expect(page.locator("input[name=nazev]")).to_have_value("Truhlářství Pokus s.r.o.")
    expect(page.get_by_role("status")).to_contain_text("Údaje načteny z ARES")
    page.fill("input[name=email]", "truhlar@example.cz")
    page.get_by_role("button", name="Uložit a založit zakázku").click()

    # 2. New job for the contact.
    expect(page).to_have_url(re.compile(r"/zakazky/nova\?kontakt=K\d{4}"))
    contact_id = page.url.rsplit("=", 1)[1]
    expect(page.locator("select[name=kontakt_id]")).to_have_value(contact_id)
    page.fill("input[name=nazev]", "Nová podlaha v dílně")
    page.select_option("select[name=stav]", "rozpracováno")
    page.get_by_role("button", name="Založit zakázku").click()
    expect(page.get_by_role("heading", name=re.compile("Nová podlaha v dílně"))).to_be_visible()
    job_url = page.url

    # 3. Invoice for the job with a live total.
    page.get_by_role("link", name="Vystavit fakturu").click()
    expect(page.locator("select[name=zakazka_id]")).to_have_value(re.compile(r"Z\d{4}-004"))
    page.locator("input[name=popis]").nth(0).fill("Pokládka podlahy")
    page.locator("input[name=mnozstvi]").nth(0).fill("12")
    page.locator("input[name=jednotka]").nth(0).fill("m²")
    page.locator("input[name=cena]").nth(0).fill("350")
    page.get_by_role("button", name="Přidat řádek").click()
    expect(page.locator("input[name=popis]")).to_have_count(4)
    page.locator("input[name=popis]").nth(1).fill("Lišty")
    page.locator("input[name=cena]").nth(1).fill("480,50")
    expect(page.locator("#soucet")).to_contain_text("4 680,50 Kč")
    page.get_by_role("button", name="Vystavit fakturu").click()

    expect(page.get_by_role("heading", name=re.compile(r"Faktura \d{8}"))).to_be_visible()
    expect(page.locator("img.qr")).to_be_visible()
    cislo = re.search(r"/faktury/(\d{8})", page.url).group(1)  # type: ignore[union-attr]

    # 4. The PDF contains the invoice number and the total.
    pdf = page.request.get(f"{demo_url}/faktury/{cislo}/pdf")
    assert pdf.headers["content-type"] == "application/pdf"
    with pdfplumber.open(io.BytesIO(pdf.body())) as doc:
        text = doc.pages[0].extract_text().replace("\xa0", " ")
    assert f"Faktura {cislo}" in text
    assert "4 680,50 Kč" in text
    assert "Truhlářství Pokus s.r.o." in text

    # 5. E-mail is not configured in the demo: the page explains what to do.
    page.get_by_role("link", name="Odeslat e-mailem").click()
    expect(page.get_by_text("Odesílání e-mailů není nastavené")).to_be_visible()
    page.go_back()

    # 6. Manual payment marks the invoice and the job as paid.
    page.fill("input[name=datum_uhrady]", date.today().isoformat())
    page.get_by_role("button", name="Označit jako uhrazenou").click()
    expect(page.locator("h1 .badge")).to_have_text("uhrazena")
    page.goto(job_url)
    expect(page.locator("select[name=stav]")).to_have_value("uhrazeno")


def test_cancel_invoice(page: Page, demo_url: str) -> None:
    login(page, demo_url)
    page.goto(demo_url + "/faktury?stav=neuhrazene")
    page.locator("table.list tbody a").first.click()
    page.fill("input[name=duvod]", "Chybná částka")
    page.get_by_role("button", name="Stornovat fakturu").click()
    expect(page.get_by_text("Stornováno: Chybná částka")).to_be_visible()
    expect(page.locator("img.qr")).to_have_count(0)


def test_dashboard_shows_overdue_and_warnings(page: Page, demo_url: str) -> None:
    login(page, demo_url)
    expect(page.get_by_text("Po splatnosti:")).to_be_visible()
    expect(page.get_by_text("Dokončené bez faktury:")).to_be_visible()
    expect(page.get_by_role("link", name=re.compile("Výměna okapů"))).to_be_visible()
