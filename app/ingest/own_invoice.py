"""Invoices the user issued elsewhere (e.g. in Air Bank internet banking).

Such a document carries the user's own IČO as the supplier and asks for payment to the
user's own account. Instead of a received document it is taken over into the issued
invoices under its original number.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pypdfium2 as pdfium

from app.ares.ico import normalize_ico, validate_ico
from app.banks.ucet import AccountError, parse_cz_account
from app.ingest.model import Extraction

OWN_INVOICE = "vydaná faktura"
_ICO_RE = re.compile(r"\bI[ČC]O?\s*[:.]?\s*(\d{8})\b", re.IGNORECASE)
_PSC_CITY_RE = re.compile(r"^(\d{3}\s?\d{2})\s+(.+)$")


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def is_own_document(ex: Extraction, own_ico: str, own_account: str, own_iban: str) -> bool:
    """Own IČO on the document and payment requested to the own account."""
    text = ex.text
    if not own_ico or not text:
        return False
    icos = {normalize_ico(m.group(1)) for m in _ICO_RE.finditer(text) if validate_ico(m.group(1))}
    if own_ico not in icos:
        return False
    flat = text.replace(" ", "")
    if own_iban and own_iban.replace(" ", "") in flat:
        return True
    if (
        ex.get("ucet")
        and own_iban
        and str(ex.get("ucet")).replace(" ", "") == own_iban.replace(" ", "")
    ):
        return True  # QR payment to the own account
    try:
        account = parse_cz_account(own_account)
    except AccountError:
        return False
    return str(account) in flat or f"{account.number}/{account.bank_code}" in flat


@dataclass
class Customer:
    nazev: str = ""
    ulice: str = ""
    psc: str = ""
    mesto: str = ""
    ico: str = ""
    lines: list[str] = field(default_factory=list)


@dataclass
class OwnInvoice:
    cislo: str
    vs: str
    datum_vystaveni: date | None
    datum_splatnosti: date | None
    castka: Decimal | None
    popis: str
    customer: Customer


def customer_block(data: bytes, own_ico: str) -> Customer:
    """Text under the "Odběratel" heading, read by position (two-column layouts)."""
    out = Customer()
    try:
        pdf = pdfium.PdfDocument(io.BytesIO(data))
    except pdfium.PdfiumError:
        return out
    try:
        page = pdf[0]
        width, _ = page.get_size()
        tp = page.get_textpage()
        search = tp.search("Odběratel", match_case=False)
        hit = search.get_next()
        if hit is None:
            return out
        left, bottom, _, top = tp.get_charbox(hit[0])
        text = tp.get_text_bounded(left=left - 12, bottom=bottom - 110, right=width, top=top + 1)
    finally:
        pdf.close()
    lines = [line.strip() for line in text.replace("\r", "").split("\n")]
    lines = [line for line in lines if line and "odběratel" not in line.lower()]
    for line in lines:
        m = _ICO_RE.search(line)
        if m and normalize_ico(m.group(1)) != own_ico and validate_ico(m.group(1)):
            out.ico = normalize_ico(m.group(1))
    address = [line for line in lines if not re.match(r"^(I[ČC]O?|DI[ČC])\b", line)]
    if address:
        out.nazev = address[0]
    for i, line in enumerate(address[1:], start=1):
        m = _PSC_CITY_RE.match(line)
        if m:
            out.psc = m.group(1).replace(" ", "")
            out.mesto = re.sub(r"\s*\(.*$", "", m.group(2)).strip()
            if i >= 2:
                out.ulice = address[i - 1]
            break
    out.lines = lines
    return out


def description(text: str) -> str:
    """Lines between "Fakturuji Vám za" (or similar) and the total."""
    m = re.search(
        r"(?:fakturuji\s+vám\s+za|fakturujeme\s+vám|předmět\s+plnění)[^\n]*\n(.*?)\n[^\n]*celkem",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return ""
    lines = [line.strip() for line in m.group(1).split("\n") if line.strip()]
    return "; ".join(lines)[:200]


def read_own_invoice(data: bytes, ex: Extraction, own_ico: str) -> OwnInvoice:
    number = str(ex.get("cislo_dodavatele") or "")
    vs = str(ex.get("vs") or _digits(number))
    amount = ex.get("castka")
    return OwnInvoice(
        cislo=number,
        vs=vs,
        datum_vystaveni=ex.get("datum_vystaveni"),
        datum_splatnosti=ex.get("datum_splatnosti"),
        castka=amount if isinstance(amount, Decimal) else None,
        popis=description(ex.text),
        customer=customer_block(data, own_ico),
    )
