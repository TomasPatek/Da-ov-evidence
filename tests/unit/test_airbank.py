"""Air Bank e-mail notifications (anonymized samples in tests/fixtures/airbank)."""

from __future__ import annotations

import email
from datetime import date
from decimal import Decimal
from email import policy
from email.message import EmailMessage
from pathlib import Path

import pytest

from app.banks import PARSERS, parser_for_email
from app.banks.airbank import AirBankParser
from app.banks.model import Direction

FIXTURES = Path(__file__).parents[1] / "fixtures" / "airbank"
OWN = "1000000005/3030"


def load(name: str) -> EmailMessage:
    raw = (FIXTURES / name).read_bytes()
    return email.message_from_bytes(raw, policy=policy.default)  # type: ignore[return-value]


def parse(name: str):  # type: ignore[no-untyped-def]
    mv = AirBankParser().parse_email(load(name))
    assert mv is not None
    return mv


def test_incoming_transfer() -> None:
    mv = parse("prichozi-uhrada.eml")
    assert mv.smer is Direction.IN
    assert mv.castka == Decimal("4100.00")
    assert mv.datum == date(2026, 11, 5)
    assert mv.ucet == OWN
    assert mv.protiucet == "4000000009/2010"
    assert mv.protiucet_nazev == "ZÁKAZNÍK PETR"
    assert mv.vs == "20260001"
    assert mv.zprava == "Úhrada faktury č. 20260001. Odběratel Petr Zákazník"
    assert mv.kod_transakce == "900000000004"
    assert mv.popis == "Příchozí úhrada z účtu ZÁKAZNÍK PETR číslo 4000000009/2010"
    assert mv.zdroj == "notifikace"


def test_outgoing_transfer_with_invisible_character_after_code() -> None:
    mv = parse("odchozi-uhrada.eml")
    assert mv.smer is Direction.OUT
    assert mv.castka == Decimal("1815.00")
    assert mv.protiucet == "3000000004/0800"
    assert mv.vs == "2027000123"
    assert mv.kod_transakce == "900000000001"


def test_payment_without_counter_account() -> None:
    mv = parse("platba-cvakem.eml")
    assert mv.smer is Direction.OUT
    assert mv.popis == "Platba Cvakem"
    assert mv.protiucet == "" and mv.vs == ""
    assert mv.kod_transakce == "900000000002"


def test_cash_deposit_with_blank_line_before_code() -> None:
    mv = parse("vklad-bankomat.eml")
    assert mv.smer is Direction.IN
    assert mv.castka == Decimal("3000.00")
    assert mv.popis.startswith("Vklad na aliančním bankomatu")
    assert mv.kod_transakce == "900000000003"


def test_recognised_only_from_air_bank() -> None:
    msg = load("prichozi-uhrada.eml")
    assert parser_for_email(msg) is not None
    del msg["From"]
    msg["From"] = "Podvodník <info@airbank.cz.example.net>"
    assert parser_for_email(msg) is None


def test_unrelated_mail_is_not_a_notification() -> None:
    msg = EmailMessage()
    msg["From"] = "Air Bank <info@airbank.cz>"
    msg["Subject"] = "Novinky v aplikaci"
    msg.set_content("Dobrý den, máme pro vás novinky.")
    assert parser_for_email(msg) is None
    assert AirBankParser().parse_email(msg) is None


def test_missing_code_or_amount_is_rejected() -> None:
    raw = (
        (FIXTURES / "prichozi-uhrada.eml")
        .read_text("utf-8")
        .replace("Kód transakce: 900000000004", "")
    )
    msg = email.message_from_string(raw, policy=policy.default)
    assert AirBankParser().parse_email(msg) is None  # type: ignore[arg-type]


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("*.eml")))
def test_every_sample_parses(name: str) -> None:
    assert parse(name).ucet == OWN


def test_registry() -> None:
    assert any(isinstance(p, AirBankParser) for p in PARSERS)
