"""Tangible assets (``majetek.csv``) and their tax depreciation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.money import ZERO, sum_money
from app.storage import CsvTable, Record, Storage
from app.storage.csvformat import Column, ColumnKind, TableSchema
from app.tax.depreciation import (
    GROUPS,
    THRESHOLD,
    DepreciationError,
    Method,
    YearRow,
    schedule,
)

MAJETEK_SCHEMA = TableSchema(
    name="majetek.csv",
    description=(
        "Karty hmotného majetku nad 80 000 Kč. Odpisy se počítají podle odpisové skupiny "
        "a způsobu a do základu daně se připočítávají v ročním přehledu."
    ),
    columns=(
        Column("id", description="Neměnný identifikátor `M0001`."),
        Column("nazev", description="Název majetku."),
        Column("datum_porizeni", ColumnKind.DATE, "Datum pořízení a uvedení do užívání."),
        Column("vstupni_cena", ColumnKind.MONEY, "Vstupní cena včetně DPH (neplátce)."),
        Column("odpisova_skupina", ColumnKind.INT, "Odpisová skupina 1–6 (§ 30 ZDP)."),
        Column("zpusob_odpisu", description="`rovnoměrný` (§ 31) nebo `zrychlený` (§ 32)."),
        Column(
            "datum_vyrazeni", ColumnKind.DATE, "Datum vyřazení (prodej, likvidace); jinak prázdné."
        ),
        Column("doklad_id", description="Přijatý doklad o pořízení, např. `PD2027-005`."),
        Column("preruseno", description="Roky, ve kterých se neodpisuje, oddělené čárkou."),
        Column("poznamka", description="Volná poznámka."),
    ),
)


class AssetError(ValueError):
    """User-facing validation error (Czech message)."""


@dataclass
class AssetDraft:
    nazev: str
    datum_porizeni: date
    vstupni_cena: Decimal
    odpisova_skupina: int
    zpusob_odpisu: str
    doklad_id: str = ""
    poznamka: str = ""


def interrupted_years(asset: Record) -> set[int]:
    return {int(y) for y in re.findall(r"\d{4}", asset.get("preruseno") or "")}


def asset_schedule(asset: Record) -> list[YearRow]:
    disposal = asset["datum_vyrazeni"].year if asset["datum_vyrazeni"] else None
    return schedule(
        asset["vstupni_cena"],
        asset["odpisova_skupina"],
        Method(asset["zpusob_odpisu"]),
        asset["datum_porizeni"].year,
        interrupted=interrupted_years(asset),
        disposal_year=disposal,
    )


class AssetBook:
    def __init__(self, storage: Storage) -> None:
        self.table: CsvTable = storage.table(MAJETEK_SCHEMA)

    def all(self) -> list[Record]:
        rows = self.table.all()
        rows.sort(key=lambda r: r["id"])
        return rows

    def get(self, asset_id: str) -> Record:
        rec = self.table.get(asset_id)
        if rec is None:
            raise AssetError("Majetek neexistuje.")
        return rec

    def _values(self, d: AssetDraft) -> Record:
        errors = []
        if not d.nazev.strip():
            errors.append("Vyplňte název majetku.")
        if d.vstupni_cena <= THRESHOLD:
            errors.append(
                "Evidují se jen věci se vstupní cenou nad 80 000 Kč; levnější jsou výdaj."
            )
        if d.odpisova_skupina not in GROUPS:
            errors.append("Vyberte odpisovou skupinu 1 až 6.")
        if d.zpusob_odpisu not in {m.value for m in Method}:
            errors.append("Vyberte způsob odpisování.")
        if errors:
            raise AssetError("\n".join(errors))
        return {
            "nazev": d.nazev.strip(),
            "datum_porizeni": d.datum_porizeni,
            "vstupni_cena": d.vstupni_cena,
            "odpisova_skupina": d.odpisova_skupina,
            "zpusob_odpisu": d.zpusob_odpisu,
            "doklad_id": d.doklad_id.strip(),
            "poznamka": d.poznamka.strip(),
        }

    def add(self, d: AssetDraft) -> Record:
        values = self._values(d)

        def factory(rows: list[Record]) -> Record:
            seq = max((int(r["id"][1:]) for r in rows if r["id"][1:].isdigit()), default=0) + 1
            return {"id": f"M{seq:04d}", "datum_vyrazeni": None, "preruseno": "", **values}

        return self.table.insert(factory)

    def update(self, asset_id: str, d: AssetDraft) -> Record:
        self.get(asset_id)
        return self.table.update(asset_id, self._values(d))

    def dispose(self, asset_id: str, when: date | None) -> Record:
        asset = self.get(asset_id)
        if when is not None and when < asset["datum_porizeni"]:
            raise AssetError("Datum vyřazení nesmí být před pořízením.")
        return self.table.update(asset_id, {"datum_vyrazeni": when})

    def toggle_interruption(self, asset_id: str, year: int) -> Record:
        asset = self.get(asset_id)
        years = interrupted_years(asset)
        years.symmetric_difference_update({year})
        return self.table.update(asset_id, {"preruseno": ",".join(str(y) for y in sorted(years))})

    def depreciation(self, year: int) -> list[tuple[Record, Decimal]]:
        """Depreciation of every asset in ``year`` (zero rows left out)."""
        out = []
        for asset in self.all():
            try:
                rows = asset_schedule(asset)
            except DepreciationError:
                continue
            amount = next((r.odpis for r in rows if r.rok == year), ZERO)
            if amount:
                out.append((asset, amount))
        return out

    def total_depreciation(self, year: int) -> Decimal:
        return sum_money(amount for _, amount in self.depreciation(year))
