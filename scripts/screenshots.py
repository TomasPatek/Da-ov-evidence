"""Regenerate screenshots in docs/img/ from demo data (requires Playwright Chromium).

Usage: ``python scripts/screenshots.py``
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo import DEMO_PASSWORD, ROOT, prepare, serve

OUT = ROOT / "docs" / "img"

SHOTS = [
    # (file, path, viewport, color scheme)
    ("prehled.png", "/", {"width": 1280, "height": 760}, "light"),
    ("prehled-tmavy.png", "/", {"width": 1280, "height": 760}, "dark"),
    ("nastaveni-mobil.png", "/nastaveni", {"width": 390, "height": 844}, "light"),
    ("faktury.png", "/faktury", {"width": 1280, "height": 760}, "light"),
    ("faktura-detail.png", "/faktury/{first}", {"width": 1280, "height": 900}, "light"),
    (
        "faktura-nova-mobil.png",
        "/faktury/nova?zakazka={job}",
        {"width": 390, "height": 844},
        "dark",
    ),
    ("zakazka-detail.png", "/zakazky/{job}", {"width": 1280, "height": 760}, "light"),
]


def first_invoice(url: str) -> str:
    # The first demo invoice is issued 40 days ago (see demo.seed).
    return f"{(date.today() - timedelta(days=40)).year}0001"


def first_job() -> str:
    return f"Z{(date.today() - timedelta(days=60)).year}-002"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory() as tmp,
        serve(prepare(Path(tmp))) as url,
        sync_playwright() as p,
    ):
        browser = p.chromium.launch()
        for name, path, viewport, scheme in SHOTS:
            ctx = browser.new_context(viewport=viewport, color_scheme=scheme)  # type: ignore[arg-type]
            page = ctx.new_page()
            page.goto(f"{url}/prihlaseni")
            page.fill("input[name=heslo]", DEMO_PASSWORD)
            page.click("button[type=submit]")
            page.goto(url + path.format(first=first_invoice(url), job=first_job()))
            page.screenshot(path=OUT / name, full_page=False)
            ctx.close()
            print(f"docs/img/{name}")
        browser.close()


if __name__ == "__main__":
    main()
