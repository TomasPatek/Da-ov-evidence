import csv
import os
import threading
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.storage import Column, ColumnKind, CsvTable, SchemaError, TableSchema
from app.storage.atomic import atomic_write_text
from app.storage.audit import AuditLog
from app.storage.csvformat import decode_text, encode_text

SCHEMA = TableSchema(
    name="test.csv",
    columns=(
        Column("id"),
        Column("nazev"),
        Column("castka", ColumnKind.MONEY),
        Column("datum", ColumnKind.DATE),
        Column("mnozstvi", ColumnKind.DECIMAL),
        Column("poradi", ColumnKind.INT),
        Column("aktivni", ColumnKind.BOOL),
    ),
)

TRICKY_TEXT = 'Žluťoučký kůň; "úpěl"\nďábelské ódy, 50 %'


@pytest.fixture
def table(tmp_path: Path) -> CsvTable:
    return CsvTable(tmp_path / "test.csv", SCHEMA)


def sample(id_: str = "1", **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": id_,
        "nazev": TRICKY_TEXT,
        "castka": Decimal("1234.50"),
        "datum": date(2026, 1, 31),
        "mnozstvi": Decimal("1.5"),
        "poradi": 3,
        "aktivni": True,
    }
    row.update(overrides)
    return row


def test_round_trip_with_tricky_text(table: CsvTable) -> None:
    table.insert(sample())
    fresh = CsvTable(table.path, SCHEMA)
    assert fresh.all() == [sample()]


def test_file_format_is_excel_friendly(table: CsvTable) -> None:
    table.insert(sample())
    raw = table.path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    assert b"\r\n" in raw  # RFC 4180 line endings
    text = raw.decode("utf-8-sig")
    rows = list(csv.reader(text.splitlines(keepends=True), delimiter=";"))
    assert rows[0] == ["id", "nazev", "castka", "datum", "mnozstvi", "poradi", "aktivni"]
    assert rows[1] == ["1", TRICKY_TEXT, "1234,50", "2026-01-31", "1,5", "3", "ano"]


def test_empty_values_round_trip(table: CsvTable) -> None:
    row = sample(nazev="", castka=None, datum=None, mnozstvi=None, poradi=None, aktivni=None)
    table.insert(row)
    assert CsvTable(table.path, SCHEMA).all() == [row]


def test_missing_file_reads_as_empty(table: CsvTable) -> None:
    assert table.all() == []
    assert table.get("x") is None


def test_insert_rejects_duplicate_id(table: CsvTable) -> None:
    table.insert(sample())
    with pytest.raises(ValueError, match="existuje"):
        table.insert(sample())


def test_insert_rejects_unknown_and_missing_columns(table: CsvTable) -> None:
    with pytest.raises(SchemaError):
        table.insert({**sample(), "navic": "x"})
    with pytest.raises(SchemaError):
        table.insert({"id": "1"})


def test_insert_rejects_float_money(table: CsvTable) -> None:
    with pytest.raises(TypeError):
        table.insert(sample(castka=12.5))


def test_insert_with_factory_sees_current_rows(table: CsvTable) -> None:
    table.insert(sample("1"))
    created = table.insert(lambda rows: sample(str(len(rows) + 1)))
    assert created["id"] == "2"
    assert [r["id"] for r in table.all()] == ["1", "2"]


def test_update_and_delete(table: CsvTable) -> None:
    table.insert(sample("1"))
    table.insert(sample("2"))
    updated = table.update("1", {"nazev": "Nový"})
    assert updated["nazev"] == "Nový"
    assert table.get("1") == sample("1", nazev="Nový")
    with pytest.raises(SchemaError):
        table.update("1", {"id": "9"})
    table.delete("2")
    assert [r["id"] for r in table.all()] == ["1"]
    with pytest.raises(KeyError):
        table.update("2", {"nazev": "x"})


def test_returned_rows_are_copies(table: CsvTable) -> None:
    table.insert(sample())
    table.all()[0]["nazev"] = "změněno"
    assert table.get("1") == sample()


def test_external_edit_is_picked_up(table: CsvTable) -> None:
    table.insert(sample())
    assert table.all()[0]["nazev"] == TRICKY_TEXT
    text = table.path.read_text(encoding="utf-8-sig").replace("1234,50", "99,00")
    atomic_write_text(table.path, "﻿" + text)
    assert table.all()[0]["castka"] == Decimal("99.00")


def test_unknown_column_in_file_is_an_error(table: CsvTable) -> None:
    table.path.write_text("﻿id;cizi\r\n1;x\r\n", encoding="utf-8")
    with pytest.raises(SchemaError, match="cizi"):
        table.all()


def test_missing_column_in_file_is_filled_and_written_back(table: CsvTable) -> None:
    # Older file without new columns: they read as empty and get added on next write.
    table.path.write_text(
        "﻿id;nazev;castka;datum;mnozstvi;poradi\r\n1;A;1,00;;;\r\n", encoding="utf-8"
    )
    assert table.get("1") == {
        "id": "1",
        "nazev": "A",
        "castka": Decimal("1.00"),
        "datum": None,
        "mnozstvi": None,
        "poradi": None,
        "aktivni": None,
    }
    table.update("1", {"aktivni": False})
    header = table.path.read_text(encoding="utf-8-sig").splitlines()[0]
    assert header.endswith(";aktivni")


def test_invalid_value_in_file_reports_line(table: CsvTable) -> None:
    table.path.write_text(
        "﻿id;nazev;castka;datum;mnozstvi;poradi;aktivni\r\n1;A;12.5;;;;\r\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match=r"řádek 2.*castka"):
        table.all()


def test_interrupted_write_keeps_original(table: CsvTable, monkeypatch: pytest.MonkeyPatch) -> None:
    table.insert(sample("1"))
    original = table.path.read_bytes()

    def boom(src: object, dst: object) -> None:
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="simulated"):
        table.insert(sample("2"))
    monkeypatch.undo()

    assert table.path.read_bytes() == original
    assert [p.name for p in table.path.parent.iterdir() if p.name.endswith(".tmp")] == []
    assert [r["id"] for r in CsvTable(table.path, SCHEMA).all()] == ["1"]


def test_concurrent_inserts_do_not_lose_rows(tmp_path: Path) -> None:
    path = tmp_path / "test.csv"
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            # Each thread uses its own table object, like separate processes would.
            t = CsvTable(path, SCHEMA)
            for i in range(10):
                t.insert(lambda rows, n=n, i=i: sample(f"{n}-{i}"))
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert errors == []
    assert len(CsvTable(path, SCHEMA).all()) == 80


@pytest.mark.parametrize(
    "text", ["=SUM(A1)", "+420 123", "-x", "@cmd", "'quoted", "\tTab", "normal", "", "x=1"]
)
def test_formula_escape_round_trip(text: str) -> None:
    encoded = encode_text(text)
    assert decode_text(encoded) == text
    if text[:1] in ("=", "+", "-", "@", "\t", "'"):
        assert encoded.startswith("'")
    else:
        assert encoded == text


def test_negative_money_is_not_escaped(table: CsvTable) -> None:
    table.insert(sample(castka=Decimal("-5.00")))
    assert ";-5,00;" in table.path.read_text(encoding="utf-8-sig")


def test_audit_records_field_changes(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.csv")
    t = CsvTable(tmp_path / "test.csv", SCHEMA, audit=audit, rel_name="2026/test.csv")
    t.insert(sample("1"))
    t.update("1", {"castka": Decimal("10.00"), "nazev": TRICKY_TEXT})  # nazev unchanged
    t.delete("1")

    entries = audit.entries()
    created = [e for e in entries if e["akce"] == "vytvoření"]
    assert {e["pole"] for e in created} == {c.name for c in SCHEMA.columns}
    changed = [e for e in entries if e["akce"] == "změna"]
    assert len(changed) == 1
    assert changed[0]["soubor"] == "2026/test.csv"
    assert changed[0]["zaznam_id"] == "1"
    assert changed[0]["pole"] == "castka"
    assert changed[0]["stara_hodnota"] == "1234,50"
    assert changed[0]["nova_hodnota"] == "10,00"
    deleted = [e for e in entries if e["akce"] == "smazání"]
    assert {e["pole"] for e in deleted} == {c.name for c in SCHEMA.columns}
    assert all(isinstance(e["cas"], datetime) for e in entries)
    assert audit.path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_audit_not_written_when_nothing_changes(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.csv")
    t = CsvTable(tmp_path / "test.csv", SCHEMA, audit=audit)
    t.insert(sample("1"))
    before = len(audit.entries())
    t.update("1", {"nazev": TRICKY_TEXT})
    assert len(audit.entries()) == before
