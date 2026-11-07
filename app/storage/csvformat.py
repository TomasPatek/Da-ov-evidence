"""CSV dialect and value codecs shared by all data files.

Format: UTF-8 with BOM, ``;`` delimiter, RFC 4180 quoting, CRLF line endings,
ISO dates, decimal comma without thousands separator.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from app import money

BOM = "﻿"
DELIMITER = ";"

# Leading characters that make spreadsheet apps treat a cell as a formula.
# Text cells starting with these (or with the escape char itself) get a leading
# apostrophe, removed again on read, so the encoding is lossless.
_FORMULA_CHARS = frozenset("=+-@\t\r'")
_ESCAPE = "'"


class SchemaError(ValueError):
    """Data does not match the declared table schema."""


class ColumnKind(StrEnum):
    TEXT = "text"
    MONEY = "money"
    DECIMAL = "decimal"
    INT = "int"
    DATE = "date"
    DATETIME = "datetime"
    BOOL = "bool"


@dataclass(frozen=True)
class Column:
    name: str
    kind: ColumnKind = ColumnKind.TEXT
    description: str = ""


@dataclass(frozen=True)
class TableSchema:
    name: str
    columns: tuple[Column, ...]
    key: str = "id"
    description: str = ""
    per_year: bool = False

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    def column(self, name: str) -> Column:
        for c in self.columns:
            if c.name == name:
                return c
        raise SchemaError(f"neznámý sloupec {name!r} v {self.name}")


BOOL_TRUE = "ano"
BOOL_FALSE = "ne"


def encode_text(text: str) -> str:
    if text and text[0] in _FORMULA_CHARS:
        return _ESCAPE + text
    return text


def decode_text(text: str) -> str:
    if text.startswith(_ESCAPE):
        return text[1:]
    return text


def encode_value(column: Column, value: Any) -> str:
    """Convert a Python value to its CSV cell text."""
    if value is None:
        return ""
    kind = column.kind
    if kind is ColumnKind.TEXT:
        if not isinstance(value, str):
            raise TypeError(f"{column.name}: očekáván text, ne {type(value).__name__}")
        return encode_text(value)
    if kind is ColumnKind.MONEY:
        return money.format_csv_amount(value)
    if kind is ColumnKind.DECIMAL:
        return money.format_csv_decimal(value)
    if kind is ColumnKind.INT:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{column.name}: očekáváno celé číslo")
        return str(value)
    if kind is ColumnKind.DATE:
        if not isinstance(value, date) or isinstance(value, datetime):
            raise TypeError(f"{column.name}: očekáváno datum")
        return value.isoformat()
    if kind is ColumnKind.DATETIME:
        if not isinstance(value, datetime):
            raise TypeError(f"{column.name}: očekáván datum a čas")
        return value.isoformat(timespec="seconds")
    if kind is ColumnKind.BOOL:
        if not isinstance(value, bool):
            raise TypeError(f"{column.name}: očekáváno ano/ne")
        return BOOL_TRUE if value else BOOL_FALSE
    raise AssertionError(kind)  # pragma: no cover


def decode_value(column: Column, text: str) -> Any:
    """Convert CSV cell text to a Python value; empty non-text cells become None."""
    kind = column.kind
    if kind is ColumnKind.TEXT:
        return decode_text(text)
    if text == "":
        return None
    if kind is ColumnKind.MONEY:
        return money.parse_csv_amount(text)
    if kind is ColumnKind.DECIMAL:
        return money.parse_csv_decimal(text)
    if kind is ColumnKind.INT:
        return int(text)
    if kind is ColumnKind.DATE:
        return date.fromisoformat(text)
    if kind is ColumnKind.DATETIME:
        return datetime.fromisoformat(text)
    if kind is ColumnKind.BOOL:
        if text == BOOL_TRUE:
            return True
        if text == BOOL_FALSE:
            return False
        raise ValueError(f"očekáváno {BOOL_TRUE}/{BOOL_FALSE}: {text!r}")
    raise AssertionError(kind)  # pragma: no cover


def render_csv(header: tuple[str, ...], rows: list[list[str]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=DELIMITER, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(header)
    writer.writerows(rows)
    return BOM + buf.getvalue()


def parse_csv(text: str) -> list[list[str]]:
    if text.startswith(BOM):
        text = text[len(BOM) :]
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=DELIMITER))
