"""Phase 0 end-to-end scenarios, run on a desktop and an iPhone-sized viewport."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

DEMO_PASSWORD = "demo-heslo-1234"


def test_login_and_logout(page: Page, demo_url: str) -> None:
    page.goto(demo_url + "/")
    expect(page).to_have_url(re.compile(r"/prihlaseni"))
    page.fill("input[name=heslo]", DEMO_PASSWORD)
    page.click("button[type=submit]")
    expect(page.get_by_role("heading", name="Přehled")).to_be_visible()
    expect(page.locator(".brand")).to_contain_text("Jana Vzorová")
    page.get_by_role("button", name="Odhlásit").click()
    expect(page).to_have_url(re.compile(r"/prihlaseni$"))


def test_wrong_password_shows_error(page: Page, demo_url: str) -> None:
    page.goto(demo_url + "/prihlaseni")
    page.fill("input[name=heslo]", "spatne-heslo")
    page.click("button[type=submit]")
    expect(page.get_by_role("alert")).to_contain_text("Nesprávné heslo")


@pytest.mark.parametrize("path", ["/", "/nastaveni", "/pruvodce/firma"])
def test_anonymous_user_sees_no_page(page: Page, demo_url: str, path: str) -> None:
    page.goto(demo_url + path)
    expect(page).to_have_url(re.compile(r"/prihlaseni"))
    expect(page.get_by_role("heading", name="Přihlášení")).to_be_visible()


def test_first_run_wizard(page: Page, fresh_url: str) -> None:
    page.goto(fresh_url + "/")
    expect(page).to_have_url(re.compile(r"/pruvodce/heslo"))
    page.fill("input[name=kod]", "DEMO0001")
    page.fill("input[name=heslo]", "nove-heslo-12345")
    page.fill("input[name=heslo2]", "nove-heslo-12345")
    page.click("button.primary")

    expect(page).to_have_url(re.compile(r"/pruvodce/firma"))
    page.fill("input[name=nazev]", "Petr Pokusný")
    page.fill("input[name=ico]", "99999994")
    page.fill("input[name=ulice]", "Zkušební 1")
    page.fill("input[name=psc]", "11000")
    page.fill("input[name=mesto]", "Praha 1")
    page.click("button.primary")

    expect(page).to_have_url(re.compile(r"/pruvodce/banka"))
    page.fill("input[name=ucet]", "1234567899/0100")
    page.click("button.primary")
    expect(page).to_have_url(re.compile(r"/pruvodce/evidence"))
    page.fill("input[name=hotovost]", "2500")
    page.fill("input[name=banka]", "48 000,50")
    page.click("button.primary")
    expect(page).to_have_url(re.compile(r"/pruvodce/posta"))
    page.click("button.primary")
    expect(page).to_have_url(re.compile(r"/pruvodce/vzhled"))
    page.click("button.primary")
    expect(page).to_have_url(re.compile(r"/pruvodce/rada"))
    page.click("button.primary")

    expect(page.get_by_role("heading", name="Přehled")).to_be_visible()
    expect(page.locator(".brand")).to_contain_text("Petr Pokusný")


def test_layout_has_no_horizontal_scroll(page: Page, demo_url: str) -> None:
    page.goto(demo_url + "/prihlaseni")
    page.fill("input[name=heslo]", DEMO_PASSWORD)
    page.click("button[type=submit]")
    for path in ("/", "/nastaveni"):
        page.goto(demo_url + path)
        overflow = page.evaluate(
            "document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        assert not overflow, path
