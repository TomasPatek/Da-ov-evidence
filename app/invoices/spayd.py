"""QR payment (SPAYD 1.0, "QR Platba" of the Czech Banking Association).

Format: ``SPD*1.0*KEY:value*KEY:value...``. Values are upper-cased ASCII
(diacritics removed, as most banking apps expect) and ``*`` is escaped as ``%2A``.
"""

from __future__ import annotations

import io
import re
import unicodedata
from datetime import date
from decimal import Decimal

import segno

from app.banks.ucet import iban_is_valid
from app.money import round_money

MAX_MESSAGE = 60
MAX_RECIPIENT = 35


class SpaydError(ValueError):
    """Payment data cannot be encoded as SPAYD."""


def _clean(text: str, limit: int) -> str:
    ascii_text = (
        unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").upper()
    )
    ascii_text = " ".join(ascii_text.split())[:limit]
    return ascii_text.replace("*", "%2A")


def build_spayd(
    iban: str,
    amount: Decimal,
    vs: str,
    message: str,
    currency: str = "CZK",
    due: date | None = None,
    recipient: str = "",
) -> str:
    iban = iban.replace(" ", "").upper()
    if not iban_is_valid(iban):
        raise SpaydError("neplatný IBAN")
    amount = round_money(amount)
    am = f"{amount:f}"
    if amount <= 0 or len(am) > 10:
        raise SpaydError("částka musí být kladná a mít nejvýše 10 znaků")
    if not re.fullmatch(r"\d{1,10}", vs):
        raise SpaydError("variabilní symbol musí mít 1 až 10 číslic")
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise SpaydError("neplatný kód měny")
    parts = ["SPD", "1.0", f"ACC:{iban}", f"AM:{am}", f"CC:{currency}"]
    if due is not None:
        parts.append(f"DT:{due:%Y%m%d}")
    if recipient:
        parts.append(f"RN:{_clean(recipient, MAX_RECIPIENT)}")
    parts.append(f"X-VS:{vs}")
    msg = _clean(message, MAX_MESSAGE)
    if msg:
        parts.append(f"MSG:{msg}")
    return "*".join(parts)


def qr_png(payload: str, scale: int = 8) -> bytes:
    buf = io.BytesIO()
    segno.make(payload, error="m", micro=False).save(buf, kind="png", scale=scale, border=4)
    return buf.getvalue()


def qr_svg(payload: str, scale: int = 4) -> str:
    buf = io.BytesIO()
    segno.make(payload, error="m", micro=False).save(
        buf, kind="svg", scale=scale, border=4, xmldecl=False, svgns=True, dark="#000"
    )
    return buf.getvalue().decode("utf-8")
