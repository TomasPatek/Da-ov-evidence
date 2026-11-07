"""Step 4: supplier templates (``sablony-dodavatelu.json``) learned from confirmed documents.

Not accounting records, so they live in JSON next to the CSV files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.ingest.model import Extraction
from app.storage.atomic import atomic_write_text, file_lock

FILE_NAME = "sablony-dodavatelu.json"
SOURCE = "šablona dodavatele"
LEARNED = ("kontakt_id", "typ", "kategorie", "popis", "zpusob_uhrady", "uhrazeno_predem")


class SupplierTemplates:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / FILE_NAME

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, ico: str) -> dict[str, Any] | None:
        return self._load().get(ico) if ico else None

    def learn(self, ico: str, values: dict[str, Any]) -> None:
        if not ico:
            return
        with file_lock(self.path):
            data = self._load()
            data[ico] = {k: values[k] for k in LEARNED if values.get(k) not in (None, "")}
            atomic_write_text(self.path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    def apply(self, ex: Extraction) -> bool:
        tpl = self.get(str(ex.get("dodavatel_ico") or ""))
        if not tpl:
            return False
        ex.steps.append(SOURCE)
        for key, value in tpl.items():
            # The description changes from document to document; offer it, but highlight it.
            ex.offer(key, value, SOURCE, certain=key != "popis")
        return True
