"""OCR step: used only for scans and photos, everything it reads is uncertain."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.ingest import ocr, pipeline
from app.ingest.files import JPEG, PDF, detect
from app.ingest.pipeline import read_document
from app.ingest.templates import SupplierTemplates

FIXTURES = Path(__file__).parents[1] / "fixtures" / "doklady"
OCR_TEXT = """Prodejna Vzor
IČO: 99990008
Účtenka č. 4711
Datum: 14.03.2027
Celkem k úhradě 389,00 Kč
Placeno hotově
"""


@pytest.fixture
def fake_ocr(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    calls: list[bytes] = []
    monkeypatch.setattr(pipeline, "OCR_ENABLED", True)
    monkeypatch.setattr(ocr.shutil, "which", lambda name: "/usr/bin/tesseract")

    def run(png: bytes) -> str:
        calls.append(png)
        return OCR_TEXT

    monkeypatch.setattr(ocr, "run_tesseract", run)
    return calls


def read(data: bytes, tmp_path: Path):  # type: ignore[no-untyped-def]
    return read_document(
        data, detect(data), "99999994", "1000000005/3030", SupplierTemplates(tmp_path), [], []
    )


def test_scan_is_read_by_ocr_and_marked_uncertain(fake_ocr: list[bytes], tmp_path: Path) -> None:
    ex = read((FIXTURES / "sken.pdf").read_bytes(), tmp_path)
    assert len(fake_ocr) == 1
    assert "OCR" in ex.steps
    assert str(ex.get("castka")) == "389.00"
    assert ex.get("dodavatel_ico") == "99990008"
    assert ex.get("datum_vystaveni") is None or "datum_vystaveni" in ex.uncertain
    assert {"castka", "dodavatel_ico"} <= ex.uncertain


def test_photo_is_rotated_upscaled_and_read(fake_ocr: list[bytes], tmp_path: Path) -> None:
    image = Image.new("RGB", (400, 600), "white")
    path = tmp_path / "foto.jpg"
    image.save(path, format="JPEG")
    ex = read(path.read_bytes(), tmp_path)
    assert detect(path.read_bytes()) is JPEG
    assert str(ex.get("castka")) == "389.00"
    prepared = Image.open(__import__("io").BytesIO(fake_ocr[0]))
    assert prepared.width >= ocr.MIN_WIDTH and prepared.mode == "L"


def test_documents_with_text_skip_ocr(fake_ocr: list[bytes], tmp_path: Path) -> None:
    read((FIXTURES / "faktura-radky.pdf").read_bytes(), tmp_path)
    assert fake_ocr == []
    assert detect((FIXTURES / "faktura-radky.pdf").read_bytes()) is PDF


def test_without_tesseract_nothing_happens(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pipeline, "OCR_ENABLED", True)
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    ex = read((FIXTURES / "sken.pdf").read_bytes(), tmp_path)
    assert "OCR" not in ex.steps


@pytest.mark.skipif(not ocr.ocr_available(), reason="tesseract not installed")
def test_real_tesseract_reads_the_scan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pipeline, "OCR_ENABLED", True)
    ex = read((FIXTURES / "sken.pdf").read_bytes(), tmp_path)
    assert "OCR" in ex.steps
    assert str(ex.get("castka")) == "1500.00"
    assert ex.get("dodavatel_ico") == "99990032"
