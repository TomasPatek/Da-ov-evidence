"""CSV-backed table: in-memory cache, atomic writes, locking and audit."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.storage.atomic import atomic_write_text, file_lock
from app.storage.audit import AuditAction, AuditLog
from app.storage.csvformat import (
    SchemaError,
    TableSchema,
    decode_value,
    encode_value,
    parse_csv,
    render_csv,
)

Record = dict[str, Any]
RecordFactory = Callable[[list[Record]], Record]

_Stamp = tuple[int, int, int]


class CsvTable:
    """One CSV file holding records with a fixed schema.

    Reads are served from memory and refreshed when the file changes on disk
    (so manual edits are picked up). Every write re-reads the file under an
    exclusive lock, applies the change and atomically replaces the file.
    """

    def __init__(
        self,
        path: Path,
        schema: TableSchema,
        audit: AuditLog | None = None,
        rel_name: str | None = None,
    ) -> None:
        self.path = path
        self.schema = schema
        self.audit = audit
        self.rel_name = rel_name or schema.name
        self._cache: list[Record] | None = None
        self._stamp: _Stamp | None = None
        # Guards the in-memory cache; the file lock guards the file itself.
        self._mem_lock = threading.RLock()

    # -- reading -----------------------------------------------------------

    def _current_stamp(self) -> _Stamp | None:
        try:
            st = self.path.stat()
        except FileNotFoundError:
            return None
        return (st.st_mtime_ns, st.st_size, st.st_ino)

    def _load(self) -> list[Record]:
        with self._mem_lock:
            return self._load_locked()

    def _load_locked(self) -> list[Record]:
        stamp = self._current_stamp()
        if self._cache is not None and stamp == self._stamp:
            return self._cache
        if stamp is None:
            records: list[Record] = []
        else:
            records = self._parse(self.path.read_text(encoding="utf-8"))
        self._cache, self._stamp = records, stamp
        return records

    def _parse(self, text: str) -> list[Record]:
        rows = parse_csv(text)
        if not rows:
            return []
        header = rows[0]
        known = set(self.schema.column_names)
        unknown = [h for h in header if h not in known]
        if unknown:
            raise SchemaError(f"{self.rel_name}: neznámé sloupce {', '.join(unknown)}")
        if self.schema.key not in header:
            raise SchemaError(f"{self.rel_name}: chybí sloupec {self.schema.key}")
        records = []
        for lineno, row in enumerate(rows[1:], start=2):
            if not any(row):
                continue
            if len(row) != len(header):
                raise SchemaError(
                    f"{self.rel_name}, řádek {lineno}: {len(row)} hodnot, čekáno {len(header)}"
                )
            cells = dict(zip(header, row, strict=True))
            record: Record = {}
            for col in self.schema.columns:
                try:
                    record[col.name] = decode_value(col, cells.get(col.name, ""))
                except (ValueError, TypeError) as exc:
                    raise SchemaError(
                        f"{self.rel_name}, řádek {lineno}, sloupec {col.name}: {exc}"
                    ) from exc
            records.append(record)
        return records

    def all(self) -> list[Record]:
        return [dict(r) for r in self._load()]

    def get(self, key: str) -> Record | None:
        for r in self._load():
            if r[self.schema.key] == key:
                return dict(r)
        return None

    # -- writing -----------------------------------------------------------

    def _validate(self, record: Record) -> None:
        names = set(self.schema.column_names)
        extra = set(record) - names
        if extra:
            raise SchemaError(f"{self.rel_name}: neznámé sloupce {sorted(extra)}")
        missing = names - set(record)
        if missing:
            raise SchemaError(f"{self.rel_name}: chybí sloupce {sorted(missing)}")
        if not record[self.schema.key]:
            raise SchemaError(f"{self.rel_name}: prázdný klíč {self.schema.key}")

    def _encode(self, record: Record) -> dict[str, str]:
        return {c.name: encode_value(c, record[c.name]) for c in self.schema.columns}

    def _write(self, records: list[Record]) -> None:
        rows = [list(self._encode(r).values()) for r in records]
        with self._mem_lock:
            atomic_write_text(self.path, render_csv(self.schema.column_names, rows))
            self._cache = [dict(r) for r in records]
            self._stamp = self._current_stamp()

    def _fresh(self) -> list[Record]:
        with self._mem_lock:
            self._cache = None
            return [dict(r) for r in self._load_locked()]

    def _index(self, records: list[Record], key: str) -> int:
        for i, r in enumerate(records):
            if r[self.schema.key] == key:
                return i
        raise KeyError(f"{self.rel_name}: záznam {key!r} neexistuje")

    def insert(self, record: Record | RecordFactory) -> Record:
        """Append a record. A factory receives current rows under the lock (for ids)."""
        with file_lock(self.path):
            records = self._fresh()
            new = dict(record(records) if callable(record) else record)
            self._validate(new)
            encoded = self._encode(new)  # type-check before touching the file
            key = new[self.schema.key]
            if any(r[self.schema.key] == key for r in records):
                raise ValueError(f"{self.rel_name}: záznam {key!r} už existuje")
            records.append(new)
            self._write(records)
            self._audit(AuditAction.CREATE, key, {}, encoded)
        return dict(new)

    def update(self, key: str, changes: Record) -> Record:
        if self.schema.key in changes and changes[self.schema.key] != key:
            raise SchemaError(f"{self.rel_name}: id záznamu nelze měnit")
        with file_lock(self.path):
            records = self._fresh()
            i = self._index(records, key)
            old = records[i]
            new = {**old, **changes}
            self._validate(new)
            old_enc, new_enc = self._encode(old), self._encode(new)
            if old_enc == new_enc:
                return dict(old)
            records[i] = new
            self._write(records)
            self._audit(AuditAction.UPDATE, key, old_enc, new_enc)
        return dict(new)

    def delete(self, key: str) -> None:
        with file_lock(self.path):
            records = self._fresh()
            i = self._index(records, key)
            old = records.pop(i)
            self._write(records)
            self._audit(AuditAction.DELETE, key, self._encode(old), {})

    def _audit(
        self, action: AuditAction, key: str, old: dict[str, str], new: dict[str, str]
    ) -> None:
        if self.audit is not None:
            self.audit.record_change(self.rel_name, key, action, old, new)
