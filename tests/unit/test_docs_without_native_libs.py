"""The CSV docs generator runs in CI without native libraries (zbar, pango)."""

from __future__ import annotations

import subprocess
import sys

BLOCK_AND_RENDER = """
import sys
for name in ("pyzbar", "pyzbar.pyzbar", "weasyprint", "pytesseract"):
    sys.modules[name] = None  # any import of these now raises ImportError
from app.storage.docs import render
assert "majetek.csv" in render()
"""


def test_docs_render_without_native_libraries() -> None:
    proc = subprocess.run(  # noqa: S603 - fixed interpreter and script
        [sys.executable, "-c", BLOCK_AND_RENDER], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
