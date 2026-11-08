"""Phase 3 scenario on desktop and iPhone: bank movements from notifications, matching."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_fakturace import login

pytestmark = pytest.mark.e2e


def test_match_and_book_movements(page: Page, demo_url: str) -> None:
    login(page, demo_url)
    expect(page.get_by_role("link", name=re.compile("Platby ke spárování"))).to_be_visible()
    page.get_by_role("link", name="Banka", exact=True).click()
    cards = page.locator("section.movement")
    expect(cards).to_have_count(5)

    # Cash deposit at an ATM: book as a transfer from the cash desk.
    deposit = cards.filter(has_text="Vklad na aliančním bankomatu")
    deposit.locator("summary").click()
    deposit.get_by_role("button", name="Vklad hotovosti z pokladny").click()
    expect(page.locator("section.movement")).to_have_count(4)

    # Card payment: book as overhead with a category.
    card = page.locator("section.movement").filter(has_text="Platba Cvakem")
    card.locator("summary").click()
    card.locator("select[name=kategorie]").select_option("19")
    card.get_by_role("button", name="Zapsat do deníku").click()
    expect(page.locator("section.movement")).to_have_count(3)

    page.goto(demo_url + "/denik")
    expect(page.locator("table.list")).to_contain_text("900000000003")
    expect(page.locator("table.list")).to_contain_text("900000000002")
    page.goto(demo_url + "/denik/et328")
    expect(page.get_by_text("Kontrolní součty sedí.")).to_be_visible()


def test_mail_page_explains_setup(page: Page, demo_url: str) -> None:
    login(page, demo_url)
    page.goto(demo_url + "/posta")
    expect(page.get_by_text("Stahování pošty není nastavené")).to_be_visible()
