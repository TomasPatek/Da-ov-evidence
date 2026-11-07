"""Invoice PDF rendered by WeasyPrint from an HTML template.

The template can be replaced by ``/config/branding/faktura.html``. It is rendered in
a sandboxed Jinja environment and WeasyPrint may only load ``data:`` URIs, so a
template can never read files or reach the network.
"""

from __future__ import annotations

import base64
from datetime import date
from decimal import Decimal
from pathlib import Path

from jinja2 import FileSystemLoader, select_autoescape
from jinja2.sandbox import SandboxedEnvironment
from weasyprint import HTML
from weasyprint.urls import URLFetcher

from app.banks.ucet import format_iban
from app.invoices.service import InvoiceView
from app.invoices.spayd import qr_svg
from app.money import format_csv_decimal, format_display_amount
from app.web.branding import logo_path, theme_path

TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_NAME = "faktura.html"


def _cz_date(value: date | None) -> str:
    return f"{value.day}. {value.month}. {value.year}" if value else ""


def _env(branding_dir: Path) -> SandboxedEnvironment:
    # A custom template in the branding folder takes precedence over the built-in one.
    env = SandboxedEnvironment(
        loader=FileSystemLoader([str(branding_dir), str(TEMPLATE_DIR)]),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["czk"] = lambda v: format_display_amount(v)
    env.filters["qty"] = lambda v: format_csv_decimal(v) if isinstance(v, Decimal) else v
    env.filters["cz_date"] = _cz_date
    env.filters["iban"] = format_iban
    return env


def _data_uri(mime: str, data: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def render_html(view: InvoiceView, branding_dir: Path) -> str:
    logo = logo_path(branding_dir)
    logo_uri = None
    if logo is not None:
        mime = "image/svg+xml" if logo.suffix == ".svg" else "image/png"
        logo_uri = _data_uri(mime, logo.read_bytes())
    qr_uri = _data_uri("image/svg+xml", qr_svg(view.spayd).encode()) if view.spayd else None
    template = _env(branding_dir).get_template(TEMPLATE_NAME)
    return template.render(
        inv=view.invoice,
        items=view.items,
        customer=view.customer,
        job=view.job,
        firma=view.firma,
        theme_css=theme_path(branding_dir).read_text(encoding="utf-8"),
        logo_uri=logo_uri,
        qr_uri=qr_uri,
    )


def render_pdf(view: InvoiceView, branding_dir: Path) -> bytes:
    html = render_html(view, branding_dir)
    fetcher = URLFetcher(allowed_protocols={"data"}, timeout=1)
    pdf: bytes = HTML(string=html, url_fetcher=fetcher).write_pdf()
    return pdf
