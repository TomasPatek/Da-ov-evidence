"""Contacts (customers and suppliers) stored in ``kontakty.csv``."""

from __future__ import annotations

from enum import StrEnum

from app.storage.csvformat import Column, ColumnKind, TableSchema
from app.storage.table import Record


class ContactType(StrEnum):
    CUSTOMER = "odběratel"
    SUPPLIER = "dodavatel"
    BOTH = "obojí"


KONTAKTY_SCHEMA = TableSchema(
    name="kontakty.csv",
    description="Odběratelé a dodavatelé. Faktury, zakázky a doklady na ně odkazují přes `id`.",
    columns=(
        Column("id", description="Neměnný identifikátor, např. `K0001`."),
        Column("typ", description="`odběratel`, `dodavatel` nebo `obojí`."),
        Column("ico", description="IČO (8 číslic), u soukromé osoby prázdné."),
        Column("dic", description="DIČ, např. `CZ12345678`."),
        Column("nazev", description="Název firmy nebo jméno a příjmení."),
        Column("ulice", description="Ulice a číslo."),
        Column("mesto", description="Obec."),
        Column("psc", description="PSČ."),
        Column("email", description="E-mail pro zasílání faktur."),
        Column("telefon", description="Telefon."),
        Column("poznamka", description="Volná poznámka."),
        Column(
            "ares_aktualizovano",
            ColumnKind.DATE,
            "Kdy byly údaje naposledy načteny z ARES; prázdné, pokud byly zadány ručně.",
        ),
    ),
)


def new_contact_id(records: list[Record]) -> str:
    numbers = [int(r["id"][1:]) for r in records if r["id"][1:].isdigit()]
    return f"K{max(numbers, default=0) + 1:04d}"


def contact_label(record: Record | None) -> str:
    return record["nazev"] if record else "(neznámý kontakt)"
