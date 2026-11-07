"""Jobs (zakázky) stored in ``zakazky.csv``."""

from __future__ import annotations

import re
from enum import StrEnum

from app.storage.csvformat import Column, ColumnKind, TableSchema
from app.storage.table import Record


class JobState(StrEnum):
    INQUIRY = "poptávka"
    IN_PROGRESS = "rozpracováno"
    DONE = "dokončeno"
    INVOICED = "vyfakturováno"
    PAID = "uhrazeno"


ZAKAZKY_SCHEMA = TableSchema(
    name="zakazky.csv",
    description="Zakázky. Faktury, doklady a platby se k nim připojují přes `zakazka_id`.",
    columns=(
        Column("id", description="Neměnný identifikátor `ZRRRR-NNN`, např. `Z2026-001`."),
        Column("kontakt_id", description="Zákazník, odkaz na `kontakty.csv`."),
        Column("nazev", description="Krátký název zakázky."),
        Column("adresa_realizace", description="Kde se zakázka provádí."),
        Column(
            "stav",
            description="`poptávka`, `rozpracováno`, `dokončeno`, `vyfakturováno` nebo `uhrazeno`.",
        ),
        Column("datum_zalozeni", ColumnKind.DATE, "Kdy byla zakázka založena."),
        Column("datum_dokonceni", ColumnKind.DATE, "Kdy byla dokončena; prázdné, dokud běží."),
        Column("poznamka", description="Volná poznámka."),
    ),
)

_JOB_ID_RE = re.compile(r"^Z(\d{4})-(\d{3,})$")


def new_job_id(records: list[Record], year: int) -> str:
    seqs = []
    for r in records:
        m = _JOB_ID_RE.match(r["id"])
        if m and int(m.group(1)) == year:
            seqs.append(int(m.group(2)))
    return f"Z{year}-{max(seqs, default=0) + 1:03d}"
