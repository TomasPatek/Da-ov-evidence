"""Step 2: QR payment (SPAYD) found in a PDF page or a photo."""

from __future__ import annotations

import contextlib
import io
import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import unquote

import pypdfium2 as pdfium
from PIL import Image
from pyzbar.pyzbar import ZBarSymbol, decode

from app.banks.ucet import iban_is_valid
from app.ingest.model import Extraction
from app.money import round_money

log = logging.getLogger(__name__)
SOURCE = "QR platba"
MAX_PAGES = 3
# Refuse absurdly large images (decompression bombs) early.
Image.MAX_IMAGE_PIXELS = 60_000_000


def parse_spayd(payload: str) -> dict[str, str] | None:
    if not payload.startswith("SPD*"):
        return None
    out: dict[str, str] = {}
    for part in payload.split("*")[2:]:
        key, sep, value = part.partition(":")
        if sep:
            out[key.upper()] = unquote(value)
    return out


def pdf_images(data: bytes, scale: float = 2.5) -> list[Image.Image]:
    images = []
    pdf = pdfium.PdfDocument(io.BytesIO(data))
    try:
        for i in range(min(len(pdf), MAX_PAGES)):
            images.append(pdf[i].render(scale=scale).to_pil())
    finally:
        pdf.close()
    return images


def find_spayd(images: list[Image.Image]) -> dict[str, str] | None:
    for image in images:
        for code in decode(image, symbols=[ZBarSymbol.QRCODE]):
            fields = parse_spayd(code.data.decode("utf-8", "replace"))
            if fields:
                return fields
    return None


def apply_spayd(fields: dict[str, str], ex: Extraction) -> None:
    ex.steps.append(SOURCE)
    acc = fields.get("ACC", "").split("+")[0]
    if iban_is_valid(acc):
        ex.offer("ucet", acc, SOURCE)
    with contextlib.suppress(InvalidOperation):
        ex.offer("castka", round_money(Decimal(fields.get("AM", ""))), SOURCE)
    ex.offer("mena", fields.get("CC", ""), SOURCE)
    ex.offer("vs", fields.get("X-VS", ""), SOURCE)
    dt = fields.get("DT", "")
    if len(dt) == 8 and dt.isdigit():
        with contextlib.suppress(ValueError):
            ex.offer("datum_splatnosti", date(int(dt[:4]), int(dt[4:6]), int(dt[6:])), SOURCE)
    ex.offer("dodavatel_nazev", fields.get("RN", "").title(), SOURCE, certain=False)


def read_qr(data: bytes, is_pdf: bool, ex: Extraction) -> bool:
    try:
        images: list[Image.Image] = pdf_images(data) if is_pdf else [Image.open(io.BytesIO(data))]
    except (pdfium.PdfiumError, OSError, Image.DecompressionBombError):
        log.info("Could not render document for QR reading")
        return False
    fields = find_spayd(images)
    if fields is None:
        return False
    apply_spayd(fields, ex)
    return True
