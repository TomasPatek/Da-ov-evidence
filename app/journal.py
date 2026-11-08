"""Cash book (peněžní deník) in ``RRRR/denik.csv`` and its ET 328 view.

Each row is one money movement on the cash desk (``hotovost``) or the business bank
account (``banka``), dated by the actual payment, not by the document. ``kategorie`` is
the ET 328 column of the movement: 9-13 for income, 15-23 for expenses, and 6/7 for
transfers between cash and bank (průběžné položky).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from app.config import FirmaConfig
from app.ingest.files import FileKind, UploadError, detect
from app.money import ZERO, parse_csv_amount, round_money, sum_money
from app.storage import Record, Storage
from app.storage.atomic import atomic_write_bytes, file_lock
from app.storage.csvformat import Column, ColumnKind, TableSchema
from app.tax.categories import Direction, categories, category

# Transit columns of ET 328: the counterpart of a transfer between cash and bank.
TRANSIT_INCOME = 6  # průběžné položky - příjmy (paired with a withdrawal from an account)
TRANSIT_EXPENSE = 7  # průběžné položky - výdaje (paired with a deposit to an account)


class Account(StrEnum):
    CASH = "hotovost"
    BANK = "banka"


class PaymentMethod(StrEnum):
    TRANSFER = "převod"
    CASH = "hotovost"
    CARD = "karta"
    QR_ON_SITE = "QR na místě"


DENIK_SCHEMA = TableSchema(
    name="denik.csv",
    per_year=True,
    description=(
        "Peněžní deník roku. Každý řádek je jeden pohyb peněz v pokladně nebo na účtu, "
        "s datem skutečné úhrady. Sloupec `kategorie` je číslo sloupce tiskopisu ET 328."
    ),
    columns=(
        Column("id", description="Neměnný identifikátor `DRRRR-NNNN`."),
        Column("datum_uhrady", ColumnKind.DATE, "Datum skutečné úhrady (ne datum vystavení)."),
        Column(
            "cislo_dokladu",
            description=(
                "Číslo dokladu ve sloupci *b* ET 328: u účtu kód transakce z notifikace banky, "
                "bez něj číslo faktury nebo přijatého dokladu, "
                "u hotovosti příjmový `PPD1/27…` nebo výdajový `VPD1/27…` pokladní doklad "
                "(číslo/dvojčíslí roku), "
                "u bankovního pohybu bez dokladu `B1…`."
            ),
        ),
        Column("doklad_id", description="Vazba na vydanou fakturu nebo přijatý doklad."),
        Column("popis", description="Text zápisu (sloupec *c* ET 328)."),
        Column("smer", description="`příjem` nebo `výdaj` (z pohledu pokladny nebo účtu)."),
        Column("castka", ColumnKind.MONEY, "Částka, vždy kladná."),
        Column("ucet", description="`hotovost` (sloupce 1–3) nebo `banka` (sloupce 4–5)."),
        Column(
            "zpusob_uhrady",
            description="`převod`, `hotovost`, `karta` nebo `QR na místě` (pro případné EET).",
        ),
        Column(
            "kategorie",
            ColumnKind.INT,
            "Sloupec ET 328: příjmy 9–13, výdaje 15–23, převod mezi pokladnou a účtem 6 nebo 7.",
        ),
        Column(
            "danove_uznatelny",
            ColumnKind.BOOL,
            "`ano`, pokud zápis ovlivňuje základ daně (sloupce 9, 10 a 15–19).",
        ),
        Column("zakazka_id", description="Zakázka, ke které zápis patří; prázdné = režie."),
        Column("poznamka", description="Volná poznámka."),
        Column(
            "priloha",
            description=(
                "Fotka nebo sken dokladu k zápisu (hlavně pokladní doklad), "
                "např. `pokladna/D2027-0004.jpg` ve složce roku; jinak prázdné."
            ),
        ),
    ),
)

ATTACHMENT_DIR = "pokladna"
_ENTRY_ID_RE = re.compile(r"^D(\d{4})-\d+$")


def attachment_kind(data: bytes) -> FileKind:
    """PDF or a photo (JPEG, PNG), detected from the content; Czech error otherwise."""
    try:
        kind = detect(data)
    except UploadError as exc:
        if not data:
            raise JournalError(str(exc)) from exc
        kind = None
    if kind is None or not (kind.is_pdf or kind.is_image):
        raise JournalError("Přiložte PDF nebo fotku dokladu (JPEG, PNG).")
    return kind


class JournalError(ValueError):
    """User-facing validation error (Czech message)."""


@dataclass
class EntryDraft:
    datum: date
    ucet: Account
    smer: str
    castka: Decimal
    kategorie: int
    popis: str
    zpusob_uhrady: PaymentMethod = PaymentMethod.TRANSFER
    doklad_id: str = ""
    zakazka_id: str = ""
    poznamka: str = ""
    # Bank "Kód transakce" (Air Bank notification); becomes the document number of bank rows.
    kod_transakce: str = ""


_TRANSACTION_CODE_RE = re.compile(r"[\w./-]{1,40}")


@dataclass
class EtRow:
    entry: Record
    columns: dict[int, Decimal]
    cash_balance: Decimal


@dataclass
class EtReport:
    year: int
    opening_cash: Decimal
    opening_bank: Decimal
    rows: list[EtRow] = field(default_factory=list)
    totals: dict[int, Decimal] = field(default_factory=dict)
    month_totals: dict[int, dict[int, Decimal]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def closing_cash(self) -> Decimal:
        return self.opening_cash + self.totals[1] - self.totals[2]

    @property
    def closing_bank(self) -> Decimal:
        return self.opening_bank + self.totals[4] - self.totals[5]

    @property
    def checks_ok(self) -> bool:
        t = self.totals
        income_ok = t[8] == sum_money(t[c] for c in range(9, 14))
        expense_ok = t[14] == sum_money(t[c] for c in range(15, 24))
        movements = t[1] - t[2] + t[4] - t[5] + t[6] - t[7]
        return income_ok and expense_ok and movements - t[8] + t[14] == ZERO

    @property
    def taxable_income(self) -> Decimal:
        return self.totals[9] + self.totals[10]

    @property
    def deductible_expenses(self) -> Decimal:
        return sum_money(self.totals[c] for c in range(15, 20))

    @property
    def profit(self) -> Decimal:
        return self.taxable_income - self.deductible_expenses


ET_COLUMNS = tuple(range(1, 24))


def _empty_columns() -> dict[int, Decimal]:
    return dict.fromkeys(ET_COLUMNS, ZERO)


def _id_seq(entry_id: str) -> int:
    m = re.match(r"^D\d{4}-(\d+)$", entry_id)
    return int(m.group(1)) if m else 0


class Journal:
    def __init__(self, storage: Storage, firma: FirmaConfig) -> None:
        self.storage = storage
        self.firma = firma

    # -- setup -------------------------------------------------------------------

    @property
    def start(self) -> date | None:
        try:
            return date.fromisoformat(self.firma.evidence.zacatek)
        except ValueError:
            return None

    @property
    def ready(self) -> bool:
        return self.start is not None

    def _opening_config(self) -> tuple[Decimal, Decimal]:
        ev = self.firma.evidence
        return parse_csv_amount(ev.pocatecni_hotovost), parse_csv_amount(ev.pocatecni_banka)

    # -- reading -----------------------------------------------------------------

    def entries(self, year: int) -> list[Record]:
        rows = self.storage.table(DENIK_SCHEMA, year).all()
        rows.sort(key=lambda r: (r["datum_uhrady"], _id_seq(r["id"])))
        return rows

    def for_document(self, doklad_id: str) -> list[Record]:
        out: list[Record] = []
        for year in self.years():
            out.extend(r for r in self.entries(year) if r["doklad_id"] == doklad_id)
        return out

    def years(self) -> list[int]:
        start = self.start
        if start is None:
            return []
        data = self.storage.data_dir
        found = {start.year}
        if data.exists():
            for p in data.iterdir():
                if (
                    p.is_dir()
                    and re.fullmatch(r"\d{4}", p.name)
                    and (p / DENIK_SCHEMA.name).exists()
                ):
                    found.add(int(p.name))
        return sorted(found)

    # -- writing -----------------------------------------------------------------

    def _validate(self, d: EntryDraft) -> None:
        start = self.start
        if start is None:
            raise JournalError("Nejdřív nastavte začátek evidence a počáteční stavy (Nastavení).")
        if d.datum < start:
            raise JournalError(
                f"Evidence v aplikaci začíná {start.day}. {start.month}. {start.year}; "
                "starší pohyby patří do původní evidence."
            )
        if d.castka <= ZERO:
            raise JournalError("Částka musí být kladná.")
        if d.smer not in (Direction.INCOME, Direction.EXPENSE):
            raise JournalError("Směr musí být příjem nebo výdaj.")
        allowed = {c.column for c in categories(Direction(d.smer))}
        allowed.add(TRANSIT_EXPENSE if d.smer == Direction.INCOME else TRANSIT_INCOME)
        if d.kategorie not in allowed:
            raise JournalError(f"Kategorie (sloupec {d.kategorie}) nepatří ke směru „{d.smer}“.")
        if (d.ucet is Account.CASH) != (d.zpusob_uhrady is PaymentMethod.CASH):
            raise JournalError(
                "Pohyb v pokladně musí mít způsob úhrady hotovost "
                "a pohyb na účtu jiný než hotovost."
            )
        if not d.popis.strip():
            raise JournalError("Vyplňte text zápisu.")
        code = d.kod_transakce.strip()
        if code and d.ucet is Account.BANK and not _TRANSACTION_CODE_RE.fullmatch(code):
            raise JournalError(
                "Kód transakce smí obsahovat jen písmena, číslice, / . - _ (do 40 znaků)."
            )

    @staticmethod
    def _number(rows: list[Record], d: EntryDraft) -> str:
        """Cash vouchers ``PPD1/27`` / ``VPD1/27`` per year; bank rows without document ``B1``."""
        if d.ucet is Account.CASH:
            prefix = "PPD" if d.smer == Direction.INCOME else "VPD"
            suffix = f"/{d.datum.year % 100:02d}"
        elif d.kod_transakce.strip():
            return d.kod_transakce.strip()
        elif d.doklad_id:
            return d.doklad_id
        else:
            prefix, suffix = "B", ""
        pattern = re.compile(rf"{prefix}(\d+){re.escape(suffix)}")
        used = [int(m.group(1)) for r in rows if (m := pattern.fullmatch(r["cislo_dokladu"]))]
        return f"{prefix}{max(used, default=0) + 1}{suffix}"

    def _record(self, rows: list[Record], d: EntryDraft, year: int) -> Record:
        transit = d.kategorie in (TRANSIT_INCOME, TRANSIT_EXPENSE)
        return {
            "id": f"D{year}-{max((_id_seq(r['id']) for r in rows), default=0) + 1:04d}",
            "datum_uhrady": d.datum,
            "cislo_dokladu": self._number(rows, d),
            "doklad_id": d.doklad_id,
            "popis": d.popis.strip(),
            "smer": d.smer,
            "castka": round_money(d.castka),
            "ucet": d.ucet.value,
            "zpusob_uhrady": d.zpusob_uhrady.value,
            "kategorie": d.kategorie,
            "danove_uznatelny": False if transit else category(d.kategorie).affects_tax_base,
            "zakazka_id": d.zakazka_id,
            "poznamka": d.poznamka.strip(),
            "priloha": "",
        }

    def add(self, d: EntryDraft) -> Record:
        self._validate(d)
        year = d.datum.year
        table = self.storage.table(DENIK_SCHEMA, year)
        return table.insert(lambda rows: self._record(rows, d, year))

    def transfer(
        self,
        when: date,
        source: Account,
        target: Account,
        amount: Decimal,
        text: str,
        kod_transakce: str = "",
    ) -> tuple[Record, Record]:
        """Move money between the cash desk and the bank account (two rows, columns 6/7)."""
        if source is target:
            raise JournalError("Převod musí být mezi pokladnou a účtem.")
        out = EntryDraft(
            when,
            source,
            Direction.EXPENSE.value,
            amount,
            TRANSIT_INCOME,
            text,
            PaymentMethod.CASH if source is Account.CASH else PaymentMethod.TRANSFER,
            kod_transakce=kod_transakce,
        )
        inn = EntryDraft(
            when,
            target,
            Direction.INCOME.value,
            amount,
            TRANSIT_EXPENSE,
            text,
            PaymentMethod.CASH if target is Account.CASH else PaymentMethod.TRANSFER,
            kod_transakce=kod_transakce,
        )
        self._validate(out)
        self._validate(inn)
        table = self.storage.table(DENIK_SCHEMA, when.year)
        with file_lock(self.storage.data_dir / str(when.year) / "denik-prevod"):
            first = table.insert(lambda rows: self._record(rows, out, when.year))
            second = table.insert(lambda rows: self._record(rows, inn, when.year))
        return first, second

    def set_number(self, entry_id: str, number: str) -> Record:
        """Replace the document number of a bank row (e.g. with the transaction code)."""
        m = re.match(r"^D(\d{4})-\d+$", entry_id)
        if not m or not _TRANSACTION_CODE_RE.fullmatch(number):
            raise JournalError("Neplatný zápis nebo číslo dokladu.")
        return self.storage.table(DENIK_SCHEMA, int(m.group(1))).update(
            entry_id, {"cislo_dokladu": number}
        )

    def delete(self, entry_id: str) -> None:
        m = re.match(r"^D(\d{4})-\d+$", entry_id)
        if not m:
            raise JournalError("Neplatný zápis.")
        table = self.storage.table(DENIK_SCHEMA, int(m.group(1)))
        row = table.get(entry_id)
        table.delete(entry_id)
        path = self.attachment_path(row) if row else None
        if path is not None:
            path.unlink(missing_ok=True)

    # -- attachments (photo of a cash document) ------------------------------------

    def get(self, entry_id: str) -> Record:
        m = _ENTRY_ID_RE.match(entry_id)
        row = self.storage.table(DENIK_SCHEMA, int(m.group(1))).get(entry_id) if m else None
        if row is None:
            raise JournalError("Zápis v deníku neexistuje.")
        return row

    def _attachment_dir(self, entry_id: str) -> Path:
        return self.storage.data_dir / entry_id[1:5] / ATTACHMENT_DIR

    def attachment_path(self, entry: Record) -> Path | None:
        """File attached to ``entry``; never anything outside the year's attachment folder."""
        name = entry.get("priloha") or ""
        if not name or not _ENTRY_ID_RE.match(str(entry.get("id", ""))):
            return None
        base = self._attachment_dir(entry["id"]).resolve()
        path = (base.parent / name).resolve()
        if path.parent != base:
            return None
        return path if path.is_file() else None

    def attach(self, entry_id: str, data: bytes) -> Record:
        """Attach (or replace) the photo or scan of the document of an entry."""
        kind = attachment_kind(data)
        entry = self.get(entry_id)
        old = self.attachment_path(entry)
        name = f"{ATTACHMENT_DIR}/{entry_id}.{kind.ext}"
        table = self.storage.table(DENIK_SCHEMA, int(entry_id[1:5]))
        # The row first: a locked year refuses the change before any file is written.
        record = table.update(entry_id, {"priloha": name})
        target = self._attachment_dir(entry_id) / f"{entry_id}.{kind.ext}"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(target, data)
        except OSError:
            table.update(entry_id, {"priloha": entry["priloha"]})
            raise
        if old is not None and old != target.resolve():
            old.unlink(missing_ok=True)
        return record

    def remove_attachment(self, entry_id: str) -> Record:
        entry = self.get(entry_id)
        path = self.attachment_path(entry)
        record = self.storage.table(DENIK_SCHEMA, int(entry_id[1:5])).update(
            entry_id, {"priloha": ""}
        )
        if path is not None:
            path.unlink(missing_ok=True)
        return record

    def remove_for_document(self, doklad_id: str) -> None:
        for r in self.for_document(doklad_id):
            self.delete(r["id"])

    # -- ET 328 ------------------------------------------------------------------

    def _opening(self, year: int) -> tuple[Decimal, Decimal]:
        start = self.start
        if start is None or year <= start.year:
            return self._opening_config()
        prev = self.et_report(year - 1)
        return prev.closing_cash, prev.closing_bank

    def et_report(self, year: int) -> EtReport:
        cash, bank = self._opening(year)
        report = EtReport(year=year, opening_cash=cash, opening_bank=bank)
        totals = _empty_columns()
        balance = cash
        negative_on: date | None = None
        for r in self.entries(year):
            cols = _empty_columns()
            amount: Decimal = r["castka"]
            income = r["smer"] == Direction.INCOME
            if r["ucet"] == Account.CASH:
                cols[1 if income else 2] = amount
                balance += amount if income else -amount
                if balance < ZERO and negative_on is None:
                    negative_on = r["datum_uhrady"]
            else:
                cols[4 if income else 5] = amount
            col = r["kategorie"]
            cols[col] = amount
            if col in range(9, 14):
                cols[8] = amount
            elif col in range(15, 24):
                cols[14] = amount
            cols[3] = balance
            report.rows.append(EtRow(entry=r, columns=cols, cash_balance=balance))
            month = report.month_totals.setdefault(r["datum_uhrady"].month, _empty_columns())
            for c in ET_COLUMNS:
                if c != 3:
                    month[c] += cols[c]
                    totals[c] += cols[c]
        totals[3] = balance
        report.totals = totals
        if negative_on is not None:
            report.warnings.append(
                f"Pokladna má od {negative_on.day}. {negative_on.month}. záporný zůstatek. "
                "Chybí příjem do pokladny, nebo je některý zápis špatně."
            )
        return report
