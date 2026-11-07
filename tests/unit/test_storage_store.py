from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.storage import Column, ColumnKind, SchemaError, Storage, TableSchema
from app.storage.csvformat import decode_value, encode_value

SCHEMA = TableSchema(name="denik.csv", columns=(Column("id"), Column("popis")))


def test_year_tables_live_in_year_folder_and_share_audit(tmp_path: Path) -> None:
    storage = Storage(tmp_path)
    storage.ensure_layout()
    t = storage.table(SCHEMA, year=2026)
    assert t is storage.table(SCHEMA, year=2026)
    t.insert({"id": "1", "popis": "x"})
    assert (tmp_path / "2026" / "denik.csv").exists()
    assert storage.audit.entries()[0]["soubor"] == "2026/denik.csv"
    storage.table(SCHEMA).insert({"id": "1", "popis": "y"})
    assert (tmp_path / "denik.csv").exists()


@pytest.mark.parametrize("year", [26, 20260, -1])
def test_invalid_year(tmp_path: Path, year: int) -> None:
    with pytest.raises(ValueError):
        Storage(tmp_path).table(SCHEMA, year=year)


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        (ColumnKind.TEXT, 5),
        (ColumnKind.INT, True),
        (ColumnKind.INT, "5"),
        (ColumnKind.DATE, datetime(2026, 1, 1)),
        (ColumnKind.DATE, "2026-01-01"),
        (ColumnKind.DATETIME, date(2026, 1, 1)),
        (ColumnKind.BOOL, 1),
        (ColumnKind.MONEY, "1,00"),
        (ColumnKind.DECIMAL, 1.5),
    ],
)
def test_encode_rejects_wrong_types(kind: ColumnKind, value: object) -> None:
    with pytest.raises(TypeError):
        encode_value(Column("x", kind), value)


def test_datetime_round_trip() -> None:
    col = Column("cas", ColumnKind.DATETIME)
    value = datetime.fromisoformat("2026-11-07T18:30:00+01:00")
    assert encode_value(col, value) == "2026-11-07T18:30:00+01:00"
    assert decode_value(col, "2026-11-07T18:30:00+01:00") == value


def test_bool_decode_rejects_other_values() -> None:
    with pytest.raises(ValueError):
        decode_value(Column("b", ColumnKind.BOOL), "true")


def test_schema_lookup() -> None:
    assert SCHEMA.column("popis").kind is ColumnKind.TEXT
    with pytest.raises(SchemaError):
        SCHEMA.column("neni")


def test_row_with_wrong_cell_count(tmp_path: Path) -> None:
    path = tmp_path / "denik.csv"
    path.write_text("﻿id;popis\r\n1;a;navic\r\n", encoding="utf-8")
    with pytest.raises(SchemaError, match="řádek 2"):
        Storage(tmp_path).table(SCHEMA).all()


def test_file_without_key_column(tmp_path: Path) -> None:
    (tmp_path / "denik.csv").write_text("﻿popis\r\na\r\n", encoding="utf-8")
    with pytest.raises(SchemaError, match="id"):
        Storage(tmp_path).table(SCHEMA).all()


def test_money_column_value_is_decimal(tmp_path: Path) -> None:
    schema = TableSchema("m.csv", (Column("id"), Column("c", ColumnKind.MONEY)))
    t = Storage(tmp_path).table(schema)
    t.insert({"id": "1", "c": Decimal("0.10")})
    assert t.get("1") == {"id": "1", "c": Decimal("0.10")}
