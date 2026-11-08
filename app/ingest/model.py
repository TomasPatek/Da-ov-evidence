"""Result of reading a received document: field values with their source and certainty."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

# Fields the pipeline can fill, in the order shown in the review form.
FIELDS = (
    "typ",
    "dodavatel_ico",
    "dodavatel_dic",
    "dodavatel_nazev",
    "cislo_dodavatele",
    "datum_vystaveni",
    "datum_splatnosti",
    "castka",
    "mena",
    "vs",
    "ucet",
    "zpusob_uhrady",
    "uhrazeno_predem",
    "kategorie",
    "popis",
    "zakazka_id",
)


@dataclass
class Extraction:
    """Values found so far. Earlier steps win; later steps only fill gaps."""

    values: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    uncertain: set[str] = field(default_factory=set)
    steps: list[str] = field(default_factory=list)
    text: str = ""

    def offer(self, name: str, value: Any, source: str, certain: bool = True) -> None:
        if value in (None, "") or name in self.values:
            return
        self.values[name] = value
        self.sources[name] = source
        if not certain:
            self.uncertain.add(name)

    def get(self, name: str) -> Any:
        return self.values.get(name)

    @property
    def amount(self) -> Decimal | None:
        value = self.values.get("castka")
        return value if isinstance(value, Decimal) else None

    @property
    def issue_date(self) -> date | None:
        value = self.values.get("datum_vystaveni")
        return value if isinstance(value, date) else None

    def as_json(self) -> dict[str, Any]:
        """Plain values for golden-file tests."""
        out: dict[str, Any] = {}
        for name in FIELDS:
            if name in self.values:
                v = self.values[name]
                out[name] = (
                    v.isoformat()
                    if isinstance(v, date)
                    else str(v)
                    if isinstance(v, Decimal)
                    else v
                )
        return out
