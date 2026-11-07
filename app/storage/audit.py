"""Append-only audit log of every record change (``audit.csv``)."""

from __future__ import annotations

import os
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.storage.atomic import file_lock
from app.storage.csvformat import (
    Column,
    ColumnKind,
    TableSchema,
    decode_value,
    encode_value,
    parse_csv,
    render_csv,
)


class AuditAction(StrEnum):
    CREATE = "vytvoření"
    UPDATE = "změna"
    DELETE = "smazání"


AUDIT_SCHEMA = TableSchema(
    name="audit.csv",
    key="cas",
    description=(
        "Záznam všech změn v datových souborech. Každý změněný sloupec má vlastní řádek. "
        "Soubor se jen doplňuje, nikdy se z něj nemaže."
    ),
    columns=(
        Column("cas", ColumnKind.DATETIME, "Kdy ke změně došlo (místní čas s časovou zónou)."),
        Column("soubor", description="Cesta k souboru v `/data`, např. `2026/denik.csv`."),
        Column("zaznam_id", description="Hodnota `id` změněného záznamu."),
        Column("akce", description="`vytvoření`, `změna` nebo `smazání`."),
        Column("pole", description="Název změněného sloupce."),
        Column("stara_hodnota", description="Hodnota před změnou, tak jak byla v CSV."),
        Column("nova_hodnota", description="Hodnota po změně, tak jak je v CSV."),
    ),
)


class AuditLog:
    """One row per changed field.

    Appends (instead of rewriting the whole file) so the log stays cheap as it
    grows. Each append is a single write + fsync under the file lock.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def record_change(
        self,
        file: str,
        record_id: str,
        action: AuditAction,
        old: dict[str, str],
        new: dict[str, str],
    ) -> None:
        now = datetime.now().astimezone().replace(microsecond=0)
        rows = []
        for field in dict.fromkeys([*old, *new]):
            before, after = old.get(field, ""), new.get(field, "")
            if action is AuditAction.UPDATE and before == after:
                continue
            values: dict[str, Any] = {
                "cas": now,
                "soubor": file,
                "zaznam_id": record_id,
                "akce": str(action),
                "pole": field,
                "stara_hodnota": before,
                "nova_hodnota": after,
            }
            rows.append([encode_value(c, values[c.name]) for c in AUDIT_SCHEMA.columns])
        if rows:
            self._append(rows)

    def _append(self, rows: list[list[str]]) -> None:
        with file_lock(self.path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            new_file = not self.path.exists() or self.path.stat().st_size == 0
            text = render_csv(AUDIT_SCHEMA.column_names, rows)
            if not new_file:
                # Drop BOM + header produced by render_csv.
                text = text.split("\r\n", 1)[1]
            with open(self.path, "a", encoding="utf-8", newline="") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = parse_csv(self.path.read_text(encoding="utf-8"))
        header, body = rows[0], rows[1:]
        cols = {c.name: c for c in AUDIT_SCHEMA.columns}
        return [
            {h: decode_value(cols[h], v) for h, v in zip(header, row, strict=True)}
            for row in body
            if any(row)
        ]
