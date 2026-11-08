"""Entry point to the data directory: hands out tables wired to the audit log."""

from __future__ import annotations

import re
from pathlib import Path

from app.storage.atomic import atomic_write_text
from app.storage.audit import AuditAction, AuditLog
from app.storage.csvformat import TableSchema
from app.storage.table import CsvTable

_YEAR_RE = re.compile(r"^\d{4}$")


LOCK_MARKER = ".uzamceno"

# In a locked year these columns may still change: an invoice or a document from that
# year can be paid (or sent) later. Everything else in the year is read-only.
LOCK_EXEMPT: dict[str, frozenset[str]] = {
    "faktury-vydane.csv": frozenset({"stav", "datum_uhrady", "datum_odeslani"}),
    "doklady-prijate.csv": frozenset({"stav", "datum_uhrady", "zpusob_uhrady"}),
}


class LockedYearError(Exception):
    """Write into a locked year (message is Czech)."""

    def __init__(self, year: int) -> None:
        super().__init__(
            f"Rok {year} je uzamčený a jeho záznamy nejde měnit. "
            "Odemknout ho můžete v Nastavení → Uzamčení roku."
        )
        self.year = year


class Storage:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.audit = AuditLog(data_dir / "audit.csv")
        self._tables: dict[str, CsvTable] = {}

    def table(self, schema: TableSchema, year: int | None = None) -> CsvTable:
        """Global table (``kontakty.csv``) or per-year one (``2026/denik.csv``)."""
        guard = None
        if year is not None:
            if not _YEAR_RE.match(str(year)):
                raise ValueError(f"neplatný rok: {year}")
            rel = f"{year}/{schema.name}"
            guard = self._guard(int(year), LOCK_EXEMPT.get(schema.name, frozenset()))
        else:
            rel = schema.name
        if rel not in self._tables:
            self._tables[rel] = CsvTable(self.data_dir / rel, schema, self.audit, rel, guard)
        return self._tables[rel]

    def _guard(self, year: int, exempt: frozenset[str]):  # type: ignore[no-untyped-def]
        def check(operation: str, columns: set[str] | None) -> None:
            if not self.is_locked(year):
                return
            if operation == "update" and columns is not None and columns <= exempt:
                return
            raise LockedYearError(year)

        return check

    # -- year lock -------------------------------------------------------------------

    def is_locked(self, year: int) -> bool:
        return (self.data_dir / str(year) / LOCK_MARKER).exists()

    def locked_years(self) -> list[int]:
        if not self.data_dir.exists():
            return []
        return sorted(
            int(p.name)
            for p in self.data_dir.iterdir()
            if p.is_dir() and _YEAR_RE.match(p.name) and (p / LOCK_MARKER).exists()
        )

    def set_locked(self, year: int, locked: bool) -> None:
        marker = self.data_dir / str(year) / LOCK_MARKER
        if marker.exists() == locked:
            return
        if locked:
            atomic_write_text(marker, f"Rok {year} je uzamčený proti změnám.\n")
        else:
            marker.unlink()
        before, after = ("ne", "ano") if locked else ("ano", "ne")
        self.audit.record_change(
            f"{year}/", "rok", AuditAction.UPDATE, {"uzamceno": before}, {"uzamceno": after}
        )

    def ensure_layout(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
