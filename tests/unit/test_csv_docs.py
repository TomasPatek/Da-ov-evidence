from app.storage.csvformat import ColumnKind
from app.storage.docs import DOC_PATH, KIND_LABELS, render
from app.storage.schemas import ALL_SCHEMAS


def test_csv_format_doc_is_up_to_date() -> None:
    assert DOC_PATH.read_text(encoding="utf-8") == render(), (
        "docs/csv-format.md is stale, run: python -m app.storage.docs"
    )


def test_every_column_is_documented() -> None:
    assert set(KIND_LABELS) == set(ColumnKind)
    for schema in ALL_SCHEMAS:
        assert schema.description, schema.name
        for col in schema.columns:
            assert col.description, f"{schema.name}.{col.name}"
