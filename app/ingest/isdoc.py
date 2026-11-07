"""Step 1: structured data from an ISDOC invoice (file, ISDOCX or attachment in a PDF)."""

from __future__ import annotations

import io
import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from xml.etree.ElementTree import Element

import pypdfium2 as pdfium
from defusedxml import ElementTree as SafeET

from app.ares.ico import normalize_ico, validate_ico
from app.ingest.model import Extraction
from app.money import round_money

log = logging.getLogger(__name__)

NS = {"i": "http://isdoc.cz/namespace/2013"}
SOURCE = "ISDOC"

# ISDOC PaymentMeansCode -> payment method of the cash book.
_PAYMENT_CODES = {"10": "hotovost", "48": "karta"}


def _text(el: Element | None, path: str) -> str:
    if el is None:
        return ""
    found = el.find(path, NS)
    return (found.text or "").strip() if found is not None and found.text else ""


def _date(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _amount(text: str) -> Decimal | None:
    try:
        return round_money(Decimal(text)) if text else None
    except InvalidOperation:
        return None


def parse_isdoc(data: bytes, ex: Extraction, own_ico: str = "") -> bool:
    """Fill ``ex`` from ISDOC XML. Returns False when the data is not a usable ISDOC."""
    try:
        root = SafeET.fromstring(data)
    except Exception:
        log.info("ISDOC could not be parsed")
        return False
    if not root.tag.endswith("}Invoice"):
        return False
    ex.steps.append(SOURCE)
    supplier = root.find("i:AccountingSupplierParty/i:Party", NS)
    ico = _text(supplier, "i:PartyIdentification/i:ID")
    if validate_ico(ico) and normalize_ico(ico) != own_ico:
        ex.offer("dodavatel_ico", normalize_ico(ico), SOURCE)
    ex.offer("dodavatel_nazev", _text(supplier, "i:PartyName/i:Name"), SOURCE)
    ex.offer("dodavatel_dic", _text(supplier, "i:PartyTaxScheme/i:CompanyID"), SOURCE)
    doc_type = _text(root, "i:DocumentType")
    ex.offer("typ", "faktura" if doc_type in ("1", "") else "jiný", SOURCE)
    ex.offer("cislo_dodavatele", _text(root, "i:ID"), SOURCE)
    ex.offer("datum_vystaveni", _date(_text(root, "i:IssueDate")), SOURCE)
    ex.offer("mena", _text(root, "i:LocalCurrencyCode") or "CZK", SOURCE)
    total = root.find("i:LegalMonetaryTotal", NS)
    # A non-VAT payer books the full price including VAT.
    gross = _amount(_text(total, "i:TaxInclusiveAmount")) or _amount(
        _text(total, "i:PayableAmount")
    )
    ex.offer("castka", gross, SOURCE)
    payable = _amount(_text(total, "i:PayableAmount"))
    if gross and payable is not None and payable == 0:
        ex.offer("uhrazeno_predem", True, SOURCE)
    payment = root.find("i:PaymentMeans/i:Payment", NS)
    details = payment.find("i:Details", NS) if payment is not None else None
    ex.offer("datum_splatnosti", _date(_text(details, "i:PaymentDueDate")), SOURCE)
    ex.offer("vs", _text(details, "i:VariableSymbol"), SOURCE)
    number, bank = _text(details, "i:ID"), _text(details, "i:BankCode")
    ex.offer("ucet", f"{number}/{bank}" if number and bank else _text(details, "i:IBAN"), SOURCE)
    code = _text(payment, "i:PaymentMeansCode")
    ex.offer("zpusob_uhrady", _PAYMENT_CODES.get(code, "převod" if code else ""), SOURCE)
    lines = root.findall("i:InvoiceLines/i:InvoiceLine", NS)
    if lines:
        first = _text(lines[0], "i:Item/i:Description")
        more = f" a další ({len(lines) - 1})" if len(lines) > 1 else ""
        ex.offer("popis", f"{first}{more}"[:200], SOURCE, certain=False)
    return True


def isdoc_attachment(pdf_data: bytes) -> bytes | None:
    """ISDOC embedded in a PDF (common with Czech invoicing software)."""
    try:
        pdf = pdfium.PdfDocument(io.BytesIO(pdf_data))
    except pdfium.PdfiumError:
        return None
    try:
        for i in range(pdf.count_attachments()):
            att = pdf.get_attachment(i)
            name = att.get_name().lower()
            if name.endswith(".isdoc") or name.endswith(".xml"):
                data = bytes(att.get_data())
                if b"isdoc.cz/namespace" in data[:8192]:
                    return data
    finally:
        pdf.close()
    return None
