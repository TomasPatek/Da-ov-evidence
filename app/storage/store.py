"""Entry point to the data directory: hands out tables wired to the audit log."""

from __future__ import annotations

import re
from pathlib import Path

from app.storage.audit import AuditLog
from app.storage.csvformat import TableSchema
from app.storage.table import CsvTable

_YEAR_RE = re.compile(r"^\d{4}$")


class Storage:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.audit = AuditLog(data_dir / "audit.csv")
        self._tables: dict[str, CsvTable] = {}

    def table(self, schema: TableSchema, year: int | None = None) -> CsvTable:
        """Global table (``kontakty.csv``) or per-year one (``2026/denik.csv``)."""
        if year is not None:
            if not _YEAR_RE.match(str(year)):
                raise ValueError(f"neplatný rok: {year}")
            rel = f"{year}/{schema.name}"
        else:
            rel = schema.name
        if rel not in self._tables:
            self._tables[rel] = CsvTable(self.data_dir / rel, schema, self.audit, rel)
        return self._tables[rel]

    def ensure_layout(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
