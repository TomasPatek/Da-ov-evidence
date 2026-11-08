"""Pluggable bank parsers. See docs/banky.md for adding another bank."""

from __future__ import annotations

from email.message import EmailMessage

from app.banks.airbank import AirBankParser
from app.banks.model import BankParser

PARSERS: tuple[BankParser, ...] = (AirBankParser(),)


def parser_for_email(msg: EmailMessage) -> BankParser | None:
    for parser in PARSERS:
        if parser.matches_email(msg):
            return parser
    return None
