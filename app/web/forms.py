"""Small helpers for parsing HTML form values with Czech error messages."""

from __future__ import annotations

import re
from datetime import date

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
