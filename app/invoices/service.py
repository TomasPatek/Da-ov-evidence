"""Issuing and lifecycle of invoices: numbering under a lock, state changes, job updates."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.config import FirmaConfig
from app.contacts import KONTAKTY_SCHEMA
from app.invoices.numbering import next_number
from app.invoices.schemas import FAKTURY_SCHEMA, POLOZKY_SCHEMA, InvoiceState
from app.invoices.spayd import SpaydError, build_spayd
from app.invoices.totals import invoice_total, line_total
from app.jobs import ZAKAZKY_SCHEMA, JobState
from app.storage import CsvTable, Record, Storage
from app.storage.atomic import atomic_write_bytes, file_lock

CURRENCY = "CZK"
_YEAR_DIR_RE = re.compile(r"^\d{4}$")

# States from which an invoice can still be paid or cancelled.
OPEN_STATES = (InvoiceState.ISSUED, InvoiceState.SENT)


class InvoiceError(ValueError):
    """User-facing validation error (message is Czech)."""


@dataclass
class DraftLine:
    popis: str
    mnozstvi: Decimal
    jednotka: str
    cena_jednotkova: Decimal

    @property
    def celkem(self) -> Decimal:
        return line_total(self.mnozstvi, self.cena_jednotkova)


@dataclass
class InvoiceDraft:
    kontakt_id: str
    datum_vystaveni: date
    datum_splatnosti: date
    lines: list[DraftLine] = field(default_factory=list)
    zakazka_id: str = ""
    poznamka: str = ""

    @property
    def total(self) -> Decimal:
        return invoice_total(line.celkem for line in self.lines)


@dataclass
class InvoiceView:
    """Everything needed to render one invoice (detail page, PDF, ISDOC, e-mail)."""

    invoice: Record
    items: list[Record]
    customer: Record
    job: Record | None
    firma: FirmaConfig
    spayd: str | None

    @property
    def cislo(self) -> str:
        return str(self.invoice["cislo"])

    @property
    def year(self) -> int:
        return int(self.cislo[:4])


PdfRenderer = Callable[[InvoiceView], bytes]


class InvoiceService:
    def __init__(self, storage: Storage, firma: FirmaConfig) -> None:
        self.storage = storage
        self.firma = firma

    # -- reading ---------------------------------------------------------------

    def years(self) -> list[int]:
        """Years that have an invoice file, newest first."""
        data = self.storage.data_dir
        if not data.exists():
            return []
        years = [
            int(p.name)
            for p in data.iterdir()
            if p.is_dir() and _YEAR_DIR_RE.match(p.name) and (p / FAKTURY_SCHEMA.name).exists()
        ]
        return sorted(years, reverse=True)

    def invoices(self, year: int) -> list[Record]:
        return self.storage.table(FAKTURY_SCHEMA, year).all()

    def all_invoices(self) -> list[Record]:
        out: list[Record] = []
        for year in self.years():
            out.extend(self.invoices(year))
        return out

    def get(self, cislo: str) -> Record | None:
        year = _year_of(cislo)
        if year is None:
            return None
        return self.storage.table(FAKTURY_SCHEMA, year).get(cislo)

    def items(self, cislo: str) -> list[Record]:
        year = _year_of(cislo)
        if year is None:
            return []
        rows = self.storage.table(POLOZKY_SCHEMA, year).all()
        return sorted((r for r in rows if r["faktura_cislo"] == cislo), key=lambda r: r["poradi"])

    def view(self, cislo: str) -> InvoiceView | None:
        invoice = self.get(cislo)
        if invoice is None:
            return None
        customer = self.storage.table(KONTAKTY_SCHEMA).get(invoice["kontakt_id"]) or {}
        job = None
        if invoice["zakazka_id"]:
            job = self.storage.table(ZAKAZKY_SCHEMA).get(invoice["zakazka_id"])
        return InvoiceView(
            invoice=invoice,
            items=self.items(cislo),
            customer=customer,
            job=job,
            firma=self.firma,
            spayd=self.payment_qr(invoice),
        )

    def payment_qr(self, invoice: Record) -> str | None:
        if not self.firma.banka.iban or invoice["stav"] == InvoiceState.CANCELLED:
            return None
        try:
            return build_spayd(
                self.firma.banka.iban,
                invoice["castka"],
                vs=invoice["vs"],
                message=f"Faktura {invoice['cislo']}",
                currency=invoice["mena"],
                due=invoice["datum_splatnosti"],
            )
        except SpaydError:
            return None

    def pdf_path(self, invoice: Record) -> Path:
        year = _year_of(invoice["cislo"])
        return self.storage.data_dir / str(year) / "doklady" / f"{invoice['cislo']}.pdf"

    # -- issuing ---------------------------------------------------------------

    def _validate(self, draft: InvoiceDraft) -> None:
        errors = []
        if self.storage.table(KONTAKTY_SCHEMA).get(draft.kontakt_id) is None:
            errors.append("Vyberte odběratele.")
        if draft.zakazka_id:
            job = self.storage.table(ZAKAZKY_SCHEMA).get(draft.zakazka_id)
            if job is None:
                errors.append("Zakázka neexistuje.")
            elif job["kontakt_id"] != draft.kontakt_id:
                errors.append("Zakázka patří jinému zákazníkovi.")
        if not draft.lines:
            errors.append("Faktura musí mít aspoň jednu položku.")
        for i, line in enumerate(draft.lines, start=1):
            if not line.popis.strip():
                errors.append(f"Položka {i}: chybí popis.")
            if line.mnozstvi == 0:
                errors.append(f"Položka {i}: množství nesmí být nula.")
        if draft.lines:
            try:
                draft.total  # noqa: B018 - validates the sum
            except ValueError:
                errors.append("Celková částka faktury musí být kladná.")
        if draft.datum_splatnosti < draft.datum_vystaveni:
            errors.append("Datum splatnosti nesmí být dřív než datum vystavení.")
        if errors:
            raise InvoiceError("\n".join(errors))

    def _start_for(self, year: int) -> int:
        # The configured start number only applies to the very first invoice in the app;
        # every later year starts again at 1.
        if any(self.invoices(y) for y in self.years() if y != year):
            return 1
        return self.firma.fakturace.pocatecni_cislo

    def issue(self, draft: InvoiceDraft, render_pdf: PdfRenderer | None = None) -> Record:
        self._validate(draft)
        year = draft.datum_vystaveni.year
        fmt = self.firma.fakturace.format_cisla
        invoices = self.storage.table(FAKTURY_SCHEMA, year)
        items = self.storage.table(POLOZKY_SCHEMA, year)
        lock_target = self.storage.data_dir / str(year) / "faktury-vydane-cislovani"
        # One lock around number allocation and both files keeps the series gap-free
        # even when two invoices are issued at the same moment.
        with file_lock(lock_target):
            existing = invoices.all()
            last = max((r["datum_vystaveni"] for r in existing), default=None)
            if last is not None and draft.datum_vystaveni < last:
                raise InvoiceError(
                    "Datum vystavení nesmí být dřív než u poslední faktury roku "
                    f"({last.day}. {last.month}. {last.year}), aby řada šla popořadě."
                )
            cislo = next_number(
                (r["cislo"] for r in existing), year, fmt, start=self._start_for(year)
            )
            # Items first: a crash in between leaves orphan items (removed here on retry),
            # never an invoice without items.
            for orphan in [r for r in items.all() if r["faktura_cislo"] == cislo]:
                items.delete(orphan["id"])
            for poradi, line in enumerate(draft.lines, start=1):
                items.insert(
                    {
                        "id": f"{cislo}-{poradi}",
                        "faktura_cislo": cislo,
                        "poradi": poradi,
                        "popis": line.popis.strip(),
                        "mnozstvi": line.mnozstvi,
                        "jednotka": line.jednotka.strip(),
                        "cena_jednotkova": line.cena_jednotkova,
                        "celkem": line.celkem,
                    }
                )
            record = invoices.insert(
                {
                    "cislo": cislo,
                    "kontakt_id": draft.kontakt_id,
                    "zakazka_id": draft.zakazka_id,
                    "datum_vystaveni": draft.datum_vystaveni,
                    "datum_splatnosti": draft.datum_splatnosti,
                    "vs": cislo,
                    "castka": draft.total,
                    "mena": CURRENCY,
                    "stav": InvoiceState.ISSUED.value,
                    "datum_odeslani": None,
                    "datum_uhrady": None,
                    "duvod_storna": "",
                    "soubor_pdf": "",
                    "poznamka": draft.poznamka.strip(),
                }
            )
        if draft.zakazka_id:
            self._set_job_state(
                draft.zakazka_id,
                JobState.INVOICED,
                only_from=(JobState.INQUIRY, JobState.IN_PROGRESS, JobState.DONE),
            )
        if render_pdf is not None:
            record = self.write_pdf(record, render_pdf)
        return record

    def write_pdf(self, invoice: Record, render_pdf: PdfRenderer) -> Record:
        view = self.view(invoice["cislo"])
        if view is None:
            raise InvoiceError("Faktura neexistuje.")
        path = self.pdf_path(invoice)
        atomic_write_bytes(path, render_pdf(view))
        rel = f"doklady/{path.name}"
        if invoice["soubor_pdf"] != rel:
            invoice = self._table_for(invoice["cislo"]).update(
                invoice["cislo"], {"soubor_pdf": rel}
            )
        return invoice

    # -- lifecycle -------------------------------------------------------------

    def _table_for(self, cislo: str) -> CsvTable:
        year = _year_of(cislo)
        if year is None:
            raise InvoiceError("Neplatné číslo faktury.")
        return self.storage.table(FAKTURY_SCHEMA, year)

    def _require(self, cislo: str) -> Record:
        invoice = self.get(cislo)
        if invoice is None:
            raise InvoiceError("Faktura neexistuje.")
        return invoice

    def mark_sent(self, cislo: str, when: date) -> Record:
        invoice = self._require(cislo)
        if invoice["stav"] == InvoiceState.CANCELLED:
            raise InvoiceError("Stornovanou fakturu nelze odeslat.")
        changes: Record = {"datum_odeslani": when}
        if invoice["stav"] == InvoiceState.ISSUED:
            changes["stav"] = InvoiceState.SENT.value
        return self._table_for(cislo).update(cislo, changes)

    def mark_paid(self, cislo: str, when: date, today: date | None = None) -> Record:
        invoice = self._require(cislo)
        if invoice["stav"] not in OPEN_STATES:
            raise InvoiceError("Uhradit lze jen vystavenou nebo odeslanou fakturu.")
        if when > (today or date.today()):
            raise InvoiceError("Datum úhrady nesmí být v budoucnosti.")
        record = self._table_for(cislo).update(
            cislo, {"stav": InvoiceState.PAID.value, "datum_uhrady": when}
        )
        self._sync_job_after_payment(record["zakazka_id"])
        return record

    def mark_unpaid(self, cislo: str) -> Record:
        """Undo a payment entered by mistake."""
        invoice = self._require(cislo)
        if invoice["stav"] != InvoiceState.PAID:
            raise InvoiceError("Faktura není uhrazená.")
        state = InvoiceState.SENT if invoice["datum_odeslani"] else InvoiceState.ISSUED
        record = self._table_for(cislo).update(cislo, {"stav": state.value, "datum_uhrady": None})
        if record["zakazka_id"]:
            self._set_job_state(record["zakazka_id"], JobState.INVOICED, only_from=(JobState.PAID,))
        return record

    def cancel(self, cislo: str, reason: str) -> Record:
        invoice = self._require(cislo)
        if invoice["stav"] not in OPEN_STATES:
            raise InvoiceError("Stornovat lze jen neuhrazenou fakturu.")
        if not reason.strip():
            raise InvoiceError("Uveďte důvod storna.")
        record = self._table_for(cislo).update(
            cislo, {"stav": InvoiceState.CANCELLED.value, "duvod_storna": reason.strip()}
        )
        job_id = record["zakazka_id"]
        if job_id:
            active = [i for i in self.job_invoices(job_id) if i["stav"] != InvoiceState.CANCELLED]
            if not active:
                self._set_job_state(job_id, JobState.DONE, only_from=(JobState.INVOICED,))
            else:
                self._sync_job_after_payment(job_id)
        return record

    # -- jobs ------------------------------------------------------------------

    def job_invoices(self, job_id: str) -> list[Record]:
        return [i for i in self.all_invoices() if i["zakazka_id"] == job_id]

    def _sync_job_after_payment(self, job_id: str) -> None:
        if not job_id:
            return
        active = [i for i in self.job_invoices(job_id) if i["stav"] != InvoiceState.CANCELLED]
        if active and all(i["stav"] == InvoiceState.PAID for i in active):
            self._set_job_state(job_id, JobState.PAID, only_from=(JobState.INVOICED,))

    def _set_job_state(self, job_id: str, state: JobState, only_from: tuple[JobState, ...]) -> None:
        jobs = self.storage.table(ZAKAZKY_SCHEMA)
        job = jobs.get(job_id)
        if job is not None and job["stav"] in only_from:
            jobs.update(job_id, {"stav": state.value})


def _year_of(cislo: str) -> int | None:
    if not re.fullmatch(r"\d{7,8}", cislo):
        return None
    return int(cislo[:4])
