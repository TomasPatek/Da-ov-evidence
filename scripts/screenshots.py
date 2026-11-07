"""Regenerate screenshots in docs/img/ from demo data (requires Playwright Chromium).

Usage: ``python scripts/screenshots.py``
"""

from __future__ import annotations

import sys
import tempfile
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
]


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
            page.goto(url + path)
            page.screenshot(path=OUT / name, full_page=False)
            ctx.close()
            print(f"docs/img/{name}")
        browser.close()


if __name__ == "__main__":
    main()
