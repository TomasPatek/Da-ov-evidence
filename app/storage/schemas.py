"""Registry of all CSV files in /data. Used to generate docs/csv-format.md."""

from __future__ import annotations

from app.assets import MAJETEK_SCHEMA
from app.banks.book import BANKA_SCHEMA
from app.contacts import KONTAKTY_SCHEMA
from app.invoices.schemas import FAKTURY_SCHEMA, POLOZKY_SCHEMA
from app.jobs import ZAKAZKY_SCHEMA
from app.journal import DENIK_SCHEMA
from app.received import DOKLADY_SCHEMA
from app.storage.audit import AUDIT_SCHEMA
from app.storage.csvformat import TableSchema

# Each phase adds its tables here (kontakty, zakázky, faktury, deník, ...).
ALL_SCHEMAS: tuple[TableSchema, ...] = (
    KONTAKTY_SCHEMA,
    ZAKAZKY_SCHEMA,
    FAKTURY_SCHEMA,
    POLOZKY_SCHEMA,
    DOKLADY_SCHEMA,
    DENIK_SCHEMA,
    BANKA_SCHEMA,
    MAJETEK_SCHEMA,
    AUDIT_SCHEMA,
)
