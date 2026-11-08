"""Small helpers for parsing HTML form values with Czech error messages."""

from __future__ import annotations

import re
from datetime import date

from starlette.datastructures import FormData, UploadFile

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PSC_RE = re.compile(r"^\d{3} ?\d{2}$")
DIC_RE = re.compile(r"^[A-Z]{2}[0-9A-Z]{2,12}$")


def parse_date(text: str, label: str, errors: list[str], required: bool = True) -> date | None:
    text = text.strip()
    if not text:
        if required:
            errors.append(f"Vyplňte {label}.")
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        errors.append(f"{label[0].upper()}{label[1:]} nemá platný tvar.")
        return None


async def read_upload(form: FormData, name: str, limit: int, errors: list[str]) -> bytes | None:
    """Optional file field: its content, or None when nothing was chosen or it is too big."""
    upload = form.get(name)
    if not isinstance(upload, UploadFile) or not upload.filename:
        return None
    data = await upload.read(limit + 1)
    if len(data) > limit:
        errors.append(f"Soubor je větší než {limit // (1024 * 1024)} MB.")
        return None
    return data


def safe_return_path(text: str, fallback: str) -> str:
    """Local path to go back to after a form (never another site)."""
    if text.startswith("/") and not text.startswith("//") and "\\" not in text:
        return text
    return fallback
