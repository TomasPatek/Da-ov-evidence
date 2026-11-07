"""Received documents (přijaté doklady) in ``RRRR/doklady-prijate.csv``.

Flow: upload -> automatic reading -> queue "ke kontrole" -> user confirms (contact,
category, job) -> paid now or later -> expense row in the cash book.
The year folder is the year the document entered the records; the cash book row is
dated by the payment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.ares.ico import normalize_ico, validate_ico
from app.config import FirmaConfig
from app.contacts import KONTAKTY_SCHEMA, ContactType, new_contact_id
from app.ingest.files import FileKind, detect
from app.ingest.model import Extraction
from app.ingest.pipeline import read_document
from app.ingest.templates import SupplierTemplates
from app.jobs import ZAKAZKY_SCHEMA
from app.journal import Account, EntryDraft, Journal, JournalError, PaymentMethod
from app.money import ZERO
from app.storage import CsvTable, Record, Storage
from app.storage.atomic import atomic_write_bytes
from app.storage.csvformat import Column, ColumnKind, TableSchema
from app.tax.categories import EXPENSE_COLUMNS, Direction


class DocState(StrEnum):
    REVIEW = "ke kontrole"
    CONFIRMED = "potvrzen"
    PAID = "uhrazen"


class DocType(StrEnum):
    INVOICE = "faktura"
    RECEIPT = "účtenka"
    OTHER = "jiný"


class DocSource(StrEnum):
    EMAIL = "e-mail"
    PHOTO = "foto"
    UPLOAD = "upload"
    MANUAL = "ručně"


DOKLADY_SCHEMA = TableSchema(
    name="doklady-prijate.csv",
    per_year=True,
    description=(
        "Přijaté doklady (faktury a účtenky od dodavatelů). Soubory leží ve složce "
        "`doklady/` roku a jmenují se podle `id`. Výdaj se do deníku zapíše při úhradě."
    ),
    columns=(
        Column("id", description="Neměnný identifikátor `PDRRRR-NNN`, např. `PD2027-001`."),
        Column("typ", description="`faktura`, `účtenka` nebo `jiný`."),
        Column("kontakt_id", description="Dodavatel, odkaz na `kontakty.csv` (po potvrzení)."),
        Column("dodavatel_ico", description="IČO dodavatele, jak bylo na dokladu."),
        Column("dodavatel_nazev", description="Název dodavatele, jak byl na dokladu."),
        Column("cislo_dodavatele", description="Číslo dokladu u dodavatele."),
        Column("datum_vystaveni", ColumnKind.DATE, "Datum vystavení."),
        Column("datum_splatnosti", ColumnKind.DATE, "Datum splatnosti."),
        Column(
            "castka", ColumnKind.MONEY, "Celková částka včetně DPH (neplátce DPH ji uplatní celou)."
        ),
        Column("mena", description="Měna, zatím jen `CZK`."),
        Column("vs", description="Variabilní symbol pro úhradu."),
        Column("ucet", description="Účet dodavatele (číslo/kód banky nebo IBAN)."),
        Column("popis", description="Co bylo nakoupeno."),
        Column("kategorie", ColumnKind.INT, "Sloupec výdajů ET 328 (15–23)."),
        Column("zakazka_id", description="Zakázka, na kterou byl nákup; prázdné = režie."),
        Column("soubor", description="Soubor dokladu, cesta v rámci složky roku."),
        Column("zdroj", description="`e-mail`, `foto`, `upload` nebo `ručně`."),
        Column("stav", description="`ke kontrole`, `potvrzen` nebo `uhrazen`."),
        Column("datum_uhrady", ColumnKind.DATE, "Kdy byl doklad zaplacen."),
        Column("zpusob_uhrady", description="`převod`, `hotovost`, `karta` nebo `QR na místě`."),
        Column(
            "nejista_pole",
            description=(
                "Pole, která aplikace přečetla nejistě (oddělená čárkou); po kontrole prázdné."
            ),
        ),
        Column("poznamka", description="Volná poznámka."),
    ),
)

EDITABLE = (
    "typ",
    "dodavatel_ico",
    "dodavatel_nazev",
    "cislo_dodavatele",
    "datum_vystaveni",
    "datum_splatnosti",
    "castka",
    "vs",
    "ucet",
    "popis",
    "kategorie",
    "zakazka_id",
    "zpusob_uhrady",
    "poznamka",
)


class ReceivedError(ValueError):
    """User-facing validation error (Czech message)."""


@dataclass
class Confirmation:
    """Values from the review form, already parsed."""

    typ: str
    dodavatel_ico: str
    dodavatel_nazev: str
    cislo_dodavatele: str
    datum_vystaveni: date | None
    datum_splatnosti: date | None
    castka: Decimal | None
    vs: str
    ucet: str
    popis: str
    kategorie: int
    zakazka_id: str
    zpusob_uhrady: str
    datum_uhrady: date | None
    poznamka: str = ""


def _seq(doc_id: str) -> int:
    m = re.match(r"^PD\d{4}-(\d+)$", doc_id)
    return int(m.group(1)) if m else 0


def year_of(doc_id: str) -> int | None:
    m = re.match(r"^PD(\d{4})-\d+$", doc_id)
    return int(m.group(1)) if m else None


class ReceivedDocs:
    def __init__(self, storage: Storage, firma: FirmaConfig) -> None:
        self.storage = storage
        self.firma = firma
        self.templates = SupplierTemplates(storage.data_dir)

    def table(self, year: int) -> CsvTable:
        return self.storage.table(DOKLADY_SCHEMA, year)

    # -- reading -------------------------------------------------------------------

    def years(self) -> list[int]:
        data = self.storage.data_dir
        if not data.exists():
            return []
        return sorted(
            (
                int(p.name)
                for p in data.iterdir()
                if p.is_dir()
                and re.fullmatch(r"\d{4}", p.name)
                and (p / DOKLADY_SCHEMA.name).exists()
            ),
            reverse=True,
        )

    def all(self) -> list[Record]:
        out: list[Record] = []
        for y in self.years():
            out.extend(self.table(y).all())
        return out

    def get(self, doc_id: str) -> Record | None:
        year = year_of(doc_id)
        return self.table(year).get(doc_id) if year else None

    def require(self, doc_id: str) -> Record:
        doc = self.get(doc_id)
        if doc is None:
            raise ReceivedError("Doklad neexistuje.")
        return doc

    def queue(self) -> list[Record]:
        return [d for d in self.all() if d["stav"] == DocState.REVIEW]

    def file_path(self, doc: Record) -> Path | None:
        if not doc["soubor"]:
            return None
        year = year_of(doc["id"])
        path = (self.storage.data_dir / str(year) / doc["soubor"]).resolve()
        base = (self.storage.data_dir / str(year) / "doklady").resolve()
        if base not in path.parents:
            return None  # never serve anything outside the documents folder
        return path if path.is_file() else None

    def for_job(self, job_id: str) -> list[Record]:
        return [d for d in self.all() if d["zakazka_id"] == job_id and d["stav"] != DocState.REVIEW]

    # -- intake --------------------------------------------------------------------

    def _new_record(self, rows: list[Record], year: int, **values: Any) -> Record:
        record: Record = {c: "" for c in DOKLADY_SCHEMA.column_names}
        record.update(
            datum_vystaveni=None,
            datum_splatnosti=None,
            datum_uhrady=None,
            castka=None,
            kategorie=None,
            mena="CZK",
        )
        record.update(values)
        record["id"] = f"PD{year}-{max((_seq(r['id']) for r in rows), default=0) + 1:03d}"
        return record

    def upload(
        self, data: bytes, source: DocSource = DocSource.UPLOAD, today: date | None = None
    ) -> Record:
        kind = detect(data)
        year = (today or date.today()).year
        ex = read_document(
            data,
            kind,
            self.firma.firma.ico,
            self.firma.banka.ucet,
            self.templates,
            self.storage.table(KONTAKTY_SCHEMA).all(),
            self.storage.table(ZAKAZKY_SCHEMA).all(),
        )
        table = self.table(year)
        values = self._values_from(ex)

        def factory(rows: list[Record]) -> Record:
            rec = self._new_record(rows, year, **values)
            rec["soubor"] = f"doklady/{rec['id']}.{kind.ext}"
            rec["zdroj"] = source.value
            rec["stav"] = DocState.REVIEW.value
            return rec

        record = table.insert(factory)
        atomic_write_bytes(self.storage.data_dir / str(year) / record["soubor"], data)
        return record

    @staticmethod
    def _values_from(ex: Extraction) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key in (*EDITABLE, "kontakt_id"):
            if key in ex.values:
                out[key] = ex.values[key]
        if ex.get("uhrazeno_predem") and ex.issue_date:
            out["datum_uhrady"] = ex.issue_date
            ex.uncertain.add("datum_uhrady")
        out["nejista_pole"] = ",".join(sorted(ex.uncertain))
        return out

    def file_kind(self, doc: Record) -> FileKind | None:
        path = self.file_path(doc)
        if path is None:
            return None
        with path.open("rb") as fh:
            head = fh.read(8192)
        try:
            return detect(head if not head.startswith(b"PK") else path.read_bytes())
        except ValueError:
            return None

    # -- confirmation ---------------------------------------------------------------

    def _validate(self, c: Confirmation, today: date) -> list[str]:
        errors = []
        if not c.dodavatel_nazev.strip():
            errors.append("Vyplňte dodavatele.")
        if c.dodavatel_ico and not validate_ico(c.dodavatel_ico):
            errors.append("IČO dodavatele nemá platný kontrolní součet.")
        if c.datum_vystaveni is None:
            errors.append("Vyplňte datum vystavení.")
        if c.castka is None or c.castka <= ZERO:
            errors.append("Částka musí být kladná.")
        if c.kategorie not in {cat.column for cat in EXPENSE_COLUMNS}:
            errors.append("Vyberte kategorii výdaje.")
        if c.zpusob_uhrady not in {m.value for m in PaymentMethod}:
            errors.append("Vyberte způsob úhrady.")
        if c.zakazka_id and self.storage.table(ZAKAZKY_SCHEMA).get(c.zakazka_id) is None:
            errors.append("Zakázka neexistuje.")
        if c.datum_uhrady and c.datum_uhrady > today:
            errors.append("Datum úhrady nesmí být v budoucnosti.")
        return errors

    def _contact_for(self, c: Confirmation) -> str:
        contacts = self.storage.table(KONTAKTY_SCHEMA)
        ico = normalize_ico(c.dodavatel_ico) if c.dodavatel_ico else ""
        for row in contacts.all():
            if (ico and row["ico"] == ico) or (
                not ico and row["nazev"] == c.dodavatel_nazev.strip()
            ):
                if row["typ"] == ContactType.CUSTOMER:
                    contacts.update(row["id"], {"typ": ContactType.BOTH.value})
                return str(row["id"])
        new = contacts.insert(
            lambda rows: {
                "id": new_contact_id(rows),
                "typ": ContactType.SUPPLIER.value,
                "ico": ico,
                "dic": "",
                "nazev": c.dodavatel_nazev.strip(),
                "ulice": "",
                "mesto": "",
                "psc": "",
                "email": "",
                "telefon": "",
                "poznamka": "",
                "ares_aktualizovano": None,
            }
        )
        return str(new["id"])

    def confirm(self, doc_id: str | None, c: Confirmation, today: date | None = None) -> Record:
        """Confirm a queued document, save a manual one (doc_id None) or edit a confirmed one."""
        errors = self._validate(c, today or date.today())
        if errors:
            raise ReceivedError("\n".join(errors))
        kontakt_id = self._contact_for(c)
        values: Record = {
            "typ": c.typ if c.typ in {t.value for t in DocType} else DocType.OTHER.value,
            "kontakt_id": kontakt_id,
            "dodavatel_ico": normalize_ico(c.dodavatel_ico) if c.dodavatel_ico else "",
            "dodavatel_nazev": c.dodavatel_nazev.strip(),
            "cislo_dodavatele": c.cislo_dodavatele.strip(),
            "datum_vystaveni": c.datum_vystaveni,
            "datum_splatnosti": c.datum_splatnosti,
            "castka": c.castka,
            "vs": c.vs.strip(),
            "ucet": c.ucet.strip(),
            "popis": c.popis.strip(),
            "kategorie": c.kategorie,
            "zakazka_id": c.zakazka_id,
            "zpusob_uhrady": c.zpusob_uhrady,
            "nejista_pole": "",
            "poznamka": c.poznamka.strip(),
            "stav": DocState.CONFIRMED.value,
            "datum_uhrady": None,
        }
        if doc_id is None:
            year = (today or date.today()).year
            record = self.table(year).insert(
                lambda rows: self._new_record(rows, year, zdroj=DocSource.MANUAL.value, **values)
            )
        else:
            self.require(doc_id)
            # Editing a paid document replaces its cash book row.
            Journal(self.storage, self.firma).remove_for_document(doc_id)
            record = self.table(year_of(doc_id) or 0).update(doc_id, values)
        self.templates.learn(values["dodavatel_ico"], values)
        if c.datum_uhrady is not None:
            record = self.pay(record["id"], c.datum_uhrady, PaymentMethod(c.zpusob_uhrady))
        return record

    def pay(self, doc_id: str, when: date, method: PaymentMethod) -> Record:
        doc = self.require(doc_id)
        if doc["stav"] == DocState.REVIEW:
            raise ReceivedError("Doklad nejdřív zkontrolujte a potvrďte.")
        journal = Journal(self.storage, self.firma)
        start = journal.start
        if start is not None and when >= start:
            try:
                journal.add(
                    EntryDraft(
                        datum=when,
                        ucet=Account.CASH if method is PaymentMethod.CASH else Account.BANK,
                        smer=Direction.EXPENSE.value,
                        castka=doc["castka"],
                        kategorie=doc["kategorie"],
                        popis=f"{doc['popis'] or 'Nákup'} – {doc['dodavatel_nazev']}"[:200],
                        zpusob_uhrady=method,
                        doklad_id=doc_id,
                        zakazka_id=doc["zakazka_id"],
                    )
                )
            except JournalError as exc:
                raise ReceivedError(str(exc)) from exc
        return self.table(year_of(doc_id) or 0).update(
            doc_id,
            {"stav": DocState.PAID.value, "datum_uhrady": when, "zpusob_uhrady": method.value},
        )

    def unpay(self, doc_id: str) -> Record:
        doc = self.require(doc_id)
        if doc["stav"] != DocState.PAID:
            raise ReceivedError("Doklad není uhrazený.")
        Journal(self.storage, self.firma).remove_for_document(doc_id)
        return self.table(year_of(doc_id) or 0).update(
            doc_id, {"stav": DocState.CONFIRMED.value, "datum_uhrady": None}
        )

    def discard(self, doc_id: str) -> None:
        """Remove a document that is still waiting for review (wrong upload, duplicate)."""
        doc = self.require(doc_id)
        if doc["stav"] != DocState.REVIEW:
            raise ReceivedError("Smazat lze jen doklad, který čeká na kontrolu.")
        path = self.file_path(doc)
        self.table(year_of(doc_id) or 0).delete(doc_id)
        if path is not None:
            path.unlink(missing_ok=True)
