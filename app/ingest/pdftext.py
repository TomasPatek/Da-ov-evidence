"""Step 3: rules over the text layer of a PDF (IČO, dates, amount, numbers, account).

Invoices lay labels out in two common ways: ``Datum vystavení: 14.08.2026`` on one line,
or a block of labels followed by a block of values. The first gives certain values, the
second is mapped in order and marked as uncertain for the review form.
"""

from __future__ import annotations

import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation

import pypdfium2 as pdfium

from app.ares.ico import normalize_ico, validate_ico
from app.banks.ucet import AccountError, iban_is_valid, parse_cz_account
from app.ingest.model import Extraction
from app.money import round_money

SOURCE = "text PDF"
MAX_PAGES = 5

_DATE = r"(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})|(\d{4})-(\d{2})-(\d{2})"
_DATE_RE = re.compile(_DATE)
_AMOUNT_RE = re.compile(
    r"(?<![\d.,])-?\d{1,3}(?:[  ]\d{3})*[,.]\d{2}(?![\d])|(?<![\d.,])-?\d+[,.]\d{2}(?![\d])"
)
_ICO_RE = re.compile(r"\bI[ČC]O?\s*[:.]?\s*(\d{8})\b", re.IGNORECASE)
_DIC_RE = re.compile(r"\bDI[ČC]\s*[:.]?\s*(CZ\d{8,10})\b", re.IGNORECASE)
_ACCOUNT_RE = re.compile(r"(?<![\d-])((?:\d{1,6}-)?\d{2,10})\s*/\s*(\d{4})(?!\d)")
_IBAN_RE = re.compile(r"\bCZ\d{2}(?:\s?\d{4}){5}\b")

DATE_LABELS = {
    "datum_vystaveni": (r"datum\s+vystavení", r"vystaveno", r"datum\s+vyhotovení"),
    "datum_splatnosti": (r"datum\s+splatnosti", r"splatnost", r"splatné\s+dne"),
    "_duzp": (r"datum\s+(?:uskutečnění\s+)?(?:zdanitelného\s+)?(?:zd\.\s*)?plnění", r"duzp"),
}
_ANY_DATE_LABEL = re.compile(
    "|".join(p for pats in DATE_LABELS.values() for p in pats), re.IGNORECASE
)
TOTAL_LABELS = (
    r"celkem\s+k\s+úhradě",
    r"k\s+úhradě",
    r"celkem\s+k\s+zaplacení",
    r"k\s+zaplacení",
    r"celková\s+částka",
    r"celkem\s+s\s+dph(?!\s+v)",
    r"celkem\s+kč",
    r"celkem(?!\s+(?:bez|s\s+dph\s+v|k\s+úhradě))",
)
NUMBER_PATTERNS = (
    r"(?:faktura|daňový\s+doklad)[^\n]{0,30}?\b(?:č\.|číslo)\s*:?\s*([A-Z0-9][A-Z0-9/-]{2,19})",
    r"\bčíslo\s+(?:faktury|dokladu)\s*:?\s*([A-Z0-9][A-Z0-9/-]{2,19})",
    r"^\s*číslo\s*:\s*([A-Z0-9][A-Z0-9/-]{2,19})",
    r"faktura[^\n]{0,30}?\bčíslo\s*:\s*([A-Z0-9][A-Z0-9/-]{2,19})",
    r"^\s*faktura\s+(?:č\.\s*)?([A-Z0-9]*\d[A-Z0-9/-]{1,19})\s*$",
)


def pdf_text(data: bytes) -> str:
    pdf = pdfium.PdfDocument(io.BytesIO(data))
    try:
        parts = []
        for i in range(min(len(pdf), MAX_PAGES)):
            page = pdf[i].get_textpage()
            parts.append(page.get_text_range())
    finally:
        pdf.close()
    return normalize("\n".join(parts))


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ").replace("￾", "")
    return "\n".join(line.strip() for line in text.split("\n"))


def parse_date(match: re.Match[str]) -> date | None:
    g = match.groups()
    try:
        if g[0]:
            return date(int(g[2]), int(g[1]), int(g[0]))
        return date(int(g[3]), int(g[4]), int(g[5]))
    except ValueError:
        return None


def parse_amount(text: str) -> Decimal | None:
    cleaned = re.sub(r"[  ]", "", text).replace(",", ".")
    try:
        return round_money(Decimal(cleaned))
    except InvalidOperation:
        return None


def _labelled_dates(lines: list[str]) -> dict[str, tuple[date, bool]]:
    """Dates per label: same-line values are certain, block-layout values are not."""
    found: dict[str, tuple[date, bool]] = {}
    i = 0
    while i < len(lines):
        if not _ANY_DATE_LABEL.search(lines[i]):
            i += 1
            continue
        # Collect a block of consecutive label lines.
        block: list[tuple[str | None, str]] = []
        j = i
        while j < len(lines) and (
            _ANY_DATE_LABEL.search(lines[j])
            or re.match(r"^(způsob|forma)\s+úhrady", lines[j], re.IGNORECASE)
        ):
            name = next(
                (
                    n
                    for n, pats in DATE_LABELS.items()
                    if any(re.search(p, lines[j], re.IGNORECASE) for p in pats)
                ),
                None,
            )
            block.append((name, lines[j]))
            j += 1
        pending: list[str | None] = []
        for name, line in block:
            m = _DATE_RE.search(line)
            if m and name and name not in found:
                d = parse_date(m)
                if d:
                    found[name] = (d, True)
            elif not m:
                pending.append(name)
        # Values listed after the block, in the same order as the labels.
        k = j
        for name in pending:
            while k < len(lines) and not _DATE_RE.search(lines[k]):
                if not re.match(r"^[\w ]{0,20}$", lines[k]):
                    break
                k += 1
            if k >= len(lines):
                break
            m = _DATE_RE.search(lines[k])
            if not m:
                break
            d = parse_date(m)
            if name and d and name not in found:
                found[name] = (d, False)
            k += 1
        i = j
    return found


def _total(lines: list[str]) -> tuple[Decimal, bool] | None:
    for label in TOTAL_LABELS:
        rx = re.compile(label, re.IGNORECASE)
        for i, line in enumerate(lines):
            m = rx.search(line)
            if not m:
                continue
            after = line[m.end() :]
            amounts = _AMOUNT_RE.findall(after)
            if amounts:
                value = parse_amount(amounts[-1])
                if value and value > 0:
                    return value, True
            # Value on one of the next lines (table layouts).
            for nxt in lines[i + 1 : i + 3]:
                amounts = _AMOUNT_RE.findall(nxt)
                if amounts:
                    value = parse_amount(amounts[-1])
                    if value and value > 0:
                        return value, False
    amounts = [a for a in (parse_amount(x) for x in _AMOUNT_RE.findall("\n".join(lines))) if a]
    if amounts:
        return max(amounts), False
    return None


def _labelled_number(lines: list[str], label: str) -> tuple[str, bool] | None:
    rx = re.compile(label, re.IGNORECASE)
    for i, line in enumerate(lines):
        m = rx.search(line)
        if not m:
            continue
        same = re.search(r"\b(\d{1,10})\b", line[m.end() :])
        if same:
            return same.group(1), True
        for nxt in lines[i + 1 : i + 4]:
            if re.fullmatch(r"\d{1,10}", nxt):
                return nxt, False
    return None


def extract_text_fields(
    text: str, ex: Extraction, own_ico: str = "", own_account: str = ""
) -> None:
    if not text.strip():
        return
    ex.steps.append(SOURCE)
    ex.text = text
    lines = [line for line in text.split("\n") if line]

    lower = text.lower()
    if "faktura" in lower or "daňový doklad" in lower:
        ex.offer("typ", "faktura", SOURCE)
    elif "účtenka" in lower or "paragon" in lower or "pokladní doklad" in lower:
        ex.offer("typ", "účtenka", SOURCE)

    icos = [
        normalize_ico(m.group(1))
        for m in _ICO_RE.finditer(text)
        if validate_ico(m.group(1)) and normalize_ico(m.group(1)) != own_ico
    ]
    if icos:
        ex.offer("dodavatel_ico", icos[0], SOURCE, certain=len(set(icos)) == 1)
    dics = [m.group(1).upper() for m in _DIC_RE.finditer(text) if m.group(1)[2:] != own_ico]
    if dics:
        ex.offer("dodavatel_dic", dics[0], SOURCE)
        # Companies have DIČ = "CZ" + IČO; use it when the IČO label is far from its value.
        if len(dics[0]) == 10 and validate_ico(dics[0][2:]):
            ex.offer("dodavatel_ico", dics[0][2:], SOURCE, certain=False)

    m = re.search(r"dodavatel\s*:?\s*([^\n]{3,80})", text, re.IGNORECASE)
    if m and not re.search(r"I[ČC]O?\s*:", m.group(1)):
        ex.offer("dodavatel_nazev", m.group(1).strip(), SOURCE, certain=False)
    elif lines:
        first = re.split(r"\s{2,}|\s+(?:objednávka|faktura)\b", lines[0], flags=re.IGNORECASE)[0]
        ex.offer("dodavatel_nazev", first.strip()[:80], SOURCE, certain=False)

    for pattern in NUMBER_PATTERNS:
        nm = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if nm:
            ex.offer("cislo_dodavatele", nm.group(1), SOURCE)
            break

    dates = _labelled_dates(lines)
    for name in ("datum_vystaveni", "datum_splatnosti"):
        if name in dates:
            value, certain = dates[name]
            ex.offer(name, value, SOURCE, certain)
    if "datum_vystaveni" not in dates and "_duzp" in dates:
        ex.offer("datum_vystaveni", dates["_duzp"][0], SOURCE, certain=False)

    total = _total(lines)
    if total:
        ex.offer("castka", total[0], SOURCE, certain=total[1])
    ex.offer(
        "mena",
        "EUR"
        if re.search(r"\bEUR\b|€", text) and "CZK" not in text and "Kč" not in text
        else "CZK",
        SOURCE,
    )

    vs = _labelled_number(lines, r"variabilní\s+symbol|\bv\.?\s?s\.?\s*:")
    if vs:
        ex.offer("vs", vs[0], SOURCE, certain=vs[1])

    own = own_account.replace(" ", "")
    for am in _ACCOUNT_RE.finditer(text):
        try:
            acc = parse_cz_account(f"{am.group(1)}/{am.group(2)}")
        except AccountError:
            continue
        if str(acc) != own:
            ex.offer("ucet", str(acc), SOURCE)
            break
    for im in _IBAN_RE.finditer(text):
        iban = im.group(0).replace(" ", "")
        if iban_is_valid(iban):
            ex.offer("ucet", iban, SOURCE)
            break

    if re.search(
        r"kartou|platební\s+kart|online|platební\s+bránu|uhrazeno|nehraďte|zaplaceno", lower
    ):
        method = "hotovost" if re.search(r"hotově|v\s+hotovosti", lower) else "karta"
        ex.offer("zpusob_uhrady", method, SOURCE, certain=False)
        ex.offer("uhrazeno_predem", True, SOURCE, certain=False)
    elif re.search(r"(?:způsob|forma)\s+úhrady\s*:?\s*(?:hotově|hotovost)", lower):
        ex.offer("zpusob_uhrady", "hotovost", SOURCE)
        ex.offer("uhrazeno_predem", True, SOURCE, certain=False)
    elif re.search(r"převodem|bankovní\s+převod|příkazem", lower):
        ex.offer("zpusob_uhrady", "převod", SOURCE)
