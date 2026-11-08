"""Air Bank: e-mail notifications "Zvýšení/Snížení zůstatku na účtu ..."."""

from __future__ import annotations

import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from email.message import EmailMessage
from email.utils import parseaddr

from app.banks.model import BankMovement, Direction, Source
from app.money import round_money

log = logging.getLogger(__name__)

SENDER_DOMAIN = "airbank.cz"
_SUBJECT_RE = re.compile(r"^(Zvýšení|Snížení) zůstatku na účtu", re.IGNORECASE)
_HEAD_RE = re.compile(
    r"na účtu .*? číslo (?P<ucet>[\d-]+/\d{4}) se (?P<smer>zvýšil|snížil) o částku "
    r"(?P<castka>[\d  ]+,\d{2}) (?P<mena>[A-Z]{3})",
    re.IGNORECASE | re.DOTALL,
)
_COUNTER_RE = re.compile(
    r"(?:z účtu|na účet)\s+(?:(?P<nazev>.*?)\s+)?číslo\s+(?P<ucet>[\d-]+/\d{4})"
)
_FIELDS = {
    "Částka": "castka",
    "Datum zaúčtování": "datum",
    "Variabilní symbol": "vs",
    "Konstantní symbol": "ks",
    "Specifický symbol": "ss",
    "Zpráva pro příjemce": "zprava",
    "Kód transakce": "kod",
}
# Invisible characters Air Bank sometimes appends to values.
_INVISIBLE = dict.fromkeys(map(ord, "﻿​‌‍⁠"), None)


def _amount(text: str) -> Decimal | None:
    try:
        return round_money(Decimal(re.sub(r"[\s ]", "", text).replace(",", ".")))
    except InvalidOperation:
        return None


def _date(text: str) -> date | None:
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text.strip())
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _body(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain",))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, UnicodeDecodeError):
        return ""
    return str(content).translate(_INVISIBLE).replace("\r\n", "\n")


class AirBankParser:
    name = "Air Bank"

    def matches_email(self, msg: EmailMessage) -> bool:
        _, address = parseaddr(str(msg.get("From", "")))
        domain = address.rpartition("@")[2].lower()
        return domain == SENDER_DOMAIN and bool(_SUBJECT_RE.match(str(msg.get("Subject", ""))))

    def parse_email(self, msg: EmailMessage) -> BankMovement | None:
        if not self.matches_email(msg):
            return None
        text = _body(msg)
        head = _HEAD_RE.search(text)
        if head is None:
            log.info("Air Bank notification without the expected first sentence")
            return None
        details = text[head.end() :].split("Pro úplnost uvádíme detaily této úhrady:", 1)[-1]
        lines = [line.strip() for line in details.split("\n")]
        values: dict[str, str] = {}
        description = ""
        for line in lines:
            if not line:
                continue
            if line.startswith("Nechceme, aby"):
                break
            key, sep, value = line.partition(":")
            if sep and key.strip() in _FIELDS:
                values[_FIELDS[key.strip()]] = value.strip()
            elif not description and not values:
                description = line
        amount = _amount(values.get("castka", "").removesuffix(head.group("mena")).strip())
        if amount is None:
            amount = _amount(head.group("castka"))
        booked = _date(values.get("datum", ""))
        code = values.get("kod", "")
        if amount is None or booked is None or not re.fullmatch(r"[\w./-]{1,40}", code):
            log.info("Air Bank notification is missing amount, date or transaction code")
            return None
        counter = _COUNTER_RE.search(description)
        return BankMovement(
            datum=booked,
            smer=Direction.IN if head.group("smer").lower() == "zvýšil" else Direction.OUT,
            castka=amount,
            ucet=head.group("ucet"),
            kod_transakce=code,
            protiucet=counter.group("ucet") if counter else "",
            protiucet_nazev=(counter.group("nazev") or "").strip() if counter else "",
            vs=values.get("vs", ""),
            ks=values.get("ks", ""),
            ss=values.get("ss", ""),
            zprava=values.get("zprava", ""),
            popis=description,
            zdroj=Source.NOTIFICATION,
        )
