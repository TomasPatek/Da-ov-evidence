"""Registry of all CSV files in /data. Used to generate docs/csv-format.md."""

from __future__ import annotations

from app.storage.audit import AUDIT_SCHEMA
from app.storage.csvformat import TableSchema

# Each phase adds its tables here (kontakty, zakázky, faktury, deník, ...).
ALL_SCHEMAS: tuple[TableSchema, ...] = (AUDIT_SCHEMA,)
