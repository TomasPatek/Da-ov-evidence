"""CSV schemas of issued invoices (per year)."""

from __future__ import annotations

from enum import StrEnum

from app.storage.csvformat import Column, ColumnKind, TableSchema


class InvoiceState(StrEnum):
    ISSUED = "vystavena"
    SENT = "odeslana"
    PAID = "uhrazena"
    CANCELLED = "stornovana"


FAKTURY_SCHEMA = TableSchema(
    name="faktury-vydane.csv",
    key="cislo",
    per_year=True,
    description=(
        "Vydané faktury roku. Vystavená faktura se nemaže, jen se stornuje. "
        "Položky jsou v `faktury-vydane-polozky.csv`."
    ),
    columns=(
        Column(
            "cislo",
            description="Číslo faktury `RRRRNNNN`, řada bez děr. Je i variabilním symbolem.",
        ),
        Column("kontakt_id", description="Odběratel, odkaz na `kontakty.csv`."),
        Column("zakazka_id", description="Zakázka, odkaz na `zakazky.csv`; může být prázdné."),
        Column("datum_vystaveni", ColumnKind.DATE, "Datum vystavení."),
        Column("datum_splatnosti", ColumnKind.DATE, "Datum splatnosti."),
        Column("vs", description="Variabilní symbol (stejný jako číslo faktury)."),
        Column("castka", ColumnKind.MONEY, "Celková částka k úhradě."),
        Column("mena", description="Měna, zatím vždy `CZK`."),
        Column("stav", description="`vystavena`, `odeslana`, `uhrazena` nebo `stornovana`."),
        Column("datum_odeslani", ColumnKind.DATE, "Kdy byla faktura odeslána e-mailem."),
        Column("datum_uhrady", ColumnKind.DATE, "Kdy byla faktura uhrazena."),
        Column("duvod_storna", description="Důvod storna; vyplněno jen u stornované faktury."),
        Column("soubor_pdf", description="PDF faktury, cesta v rámci složky roku."),
        Column("poznamka", description="Poznámka vytištěná na faktuře."),
        Column(
            "zdroj",
            description=(
                "Kde faktura vznikla: prázdné = v aplikaci, jinak např. `Air Bank` "
                "(převzatá faktura, PDF je originál a aplikace ho nemění)."
            ),
        ),
    ),
)

POLOZKY_SCHEMA = TableSchema(
    name="faktury-vydane-polozky.csv",
    per_year=True,
    description="Položky vydaných faktur. Součet `celkem` položek je `castka` faktury.",
    columns=(
        Column("id", description="Identifikátor položky `cislo-poradi`, např. `20260001-1`."),
        Column("faktura_cislo", description="Číslo faktury, odkaz na `faktury-vydane.csv`."),
        Column("poradi", ColumnKind.INT, "Pořadí položky na faktuře, od 1."),
        Column("popis", description="Text položky."),
        Column("mnozstvi", ColumnKind.DECIMAL, "Množství."),
        Column("jednotka", description="Jednotka, např. `ks`, `hod`, `m²`."),
        Column("cena_jednotkova", ColumnKind.MONEY, "Cena za jednotku."),
        Column("celkem", ColumnKind.MONEY, "Množství × cena za jednotku, zaokrouhleno na haléře."),
    ),
)
