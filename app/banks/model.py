"""A money movement on the business bank account, as reported by the bank."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from email.message import EmailMessage
from enum import StrEnum
from typing import Protocol


class Direction(StrEnum):
    IN = "příjem"
    OUT = "výdaj"


class Source(StrEnum):
    NOTIFICATION = "notifikace"
    STATEMENT = "výpis"


@dataclass(frozen=True)
class BankMovement:
    datum: date  # booking date
    smer: Direction
    castka: Decimal  # always positive
    ucet: str  # our account the movement belongs to
    kod_transakce: str  # unique id from the bank, used to merge duplicates
    protiucet: str = ""
    protiucet_nazev: str = ""
    vs: str = ""
    ks: str = ""
    ss: str = ""
    zprava: str = ""
    popis: str = ""
    zdroj: Source = Source.NOTIFICATION


class BankParser(Protocol):
    """One bank. Add a module under app/banks/ and register it in PARSERS (docs/banky.md)."""

    name: str

    def matches_email(self, msg: EmailMessage) -> bool: ...

    def parse_email(self, msg: EmailMessage) -> BankMovement | None: ...
