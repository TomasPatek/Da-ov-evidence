"""Reading a received document: ISDOC -> QR payment -> PDF text -> supplier template.

Each step only fills fields the previous ones did not find. Everything runs locally;
no document is sent to any external service.
"""

from __future__ import annotations

import logging
import re

from app.ingest.files import FileKind, isdoc_from_isdocx
from app.ingest.isdoc import isdoc_attachment, parse_isdoc
from app.ingest.model import Extraction
from app.ingest.pdftext import extract_text_fields, pdf_text
from app.ingest.qr import read_qr
from app.ingest.templates import SupplierTemplates
from app.storage import Record
from app.tax.categories import Direction, default_category

log = logging.getLogger(__name__)


def read_document(
    data: bytes,
    kind: FileKind,
    own_ico: str,
    own_account: str,
    templates: SupplierTemplates,
    contacts: list[Record],
    jobs: list[Record],
) -> Extraction:
    ex = Extraction()
    # 1. ISDOC
    xml: bytes | None = None
    if kind.ext == "isdoc":
        xml = data
    elif kind.ext == "isdocx":
        xml = isdoc_from_isdocx(data)
    elif kind.is_pdf:
        xml = isdoc_attachment(data)
    if xml is not None:
        parse_isdoc(xml, ex, own_ico)
    # 2. QR payment
    if kind.is_pdf or kind.is_image:
        read_qr(data, kind.is_pdf, ex)
    # 3. Text layer
    if kind.is_pdf:
        try:
            extract_text_fields(pdf_text(data), ex, own_ico, own_account)
        except Exception:
            log.info("PDF text layer could not be read")
    # 4. Supplier template and known contact
    templates.apply(ex)
    complete(ex, contacts, jobs)
    return ex


def complete(ex: Extraction, contacts: list[Record], jobs: list[Record]) -> None:
    """Link the supplier to a contact, suggest a job and fill defaults."""
    ico = ex.get("dodavatel_ico")
    if ico:
        contact = next((c for c in contacts if c["ico"] == ico), None)
        if contact is not None:
            ex.offer("kontakt_id", contact["id"], "kontakty")
            ex.values["dodavatel_nazev"] = contact["nazev"]
            ex.uncertain.discard("dodavatel_nazev")
    _suggest_job(ex, jobs)
    ex.offer("typ", "jiný", "výchozí", certain=False)
    ex.offer("mena", "CZK", "výchozí")
    ex.offer("kategorie", default_category(Direction.EXPENSE).column, "výchozí", certain=False)
    ex.offer("zpusob_uhrady", "převod", "výchozí", certain=False)
    if not ex.get("popis") and ex.get("dodavatel_nazev"):
        ex.offer("popis", f"Nákup – {ex.get('dodavatel_nazev')}", "výchozí", certain=False)
    for required in ("datum_vystaveni", "castka", "dodavatel_nazev"):
        if not ex.get(required):
            ex.uncertain.add(required)


def _suggest_job(ex: Extraction, jobs: list[Record]) -> None:
    active = [j for j in jobs if j["stav"] in ("poptávka", "rozpracováno", "dokončeno")]
    text = ex.text.lower()
    if text:
        for job in active:
            street = re.split(r",", job["adresa_realizace"])[0].strip().lower()
            if (street and len(street) > 4 and street in text) or (
                len(job["nazev"]) > 4 and job["nazev"].lower() in text
            ):
                ex.offer("zakazka_id", job["id"], "návrh podle textu dokladu", certain=False)
                return
    running = [j for j in active if j["stav"] == "rozpracováno"]
    if len(running) == 1:
        ex.offer("zakazka_id", running[0]["id"], "jediná rozpracovaná zakázka", certain=False)
