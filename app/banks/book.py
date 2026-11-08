"""Bank movements (``RRRR/banka.csv``) and their matching to invoices and documents.

Notifications are a fast signal, the monthly statement is the source of truth: both
carry the bank's transaction code, which merges duplicates. Matching follows the
zadání: variable symbol and amount match automatically, everything else is a
suggestion the user confirms; manual matching is always possible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.banks.model import BankMovement, Direction, Source
from app.banks.ucet import AccountError, parse_cz_account
from app.config import FirmaConfig
from app.invoices.service import OPEN_STATES, InvoiceError, InvoiceService
from app.journal import Account, EntryDraft, Journal, JournalError, PaymentMethod
from app.received import DocState, ReceivedDocs, ReceivedError
from app.storage import CsvTable, Record, Storage
from app.storage.atomic import file_lock
from app.storage.csvformat import Column, ColumnKind, TableSchema

CARD_DAYS = 5  # a card payment is booked a few days after the purchase
ATTACHED_NOTE = "kód transakce doplněn k dokladu zaplacenému kartou"


class MatchState(StrEnum):
    OPEN = "nespárováno"
    MATCHED = "spárováno"
    IGNORED = "ignorováno"


BANKA_SCHEMA = TableSchema(
    name="banka.csv",
    per_year=True,
    description=(
        "Pohyby na podnikatelském účtu z notifikací a výpisů banky. Stejná transakce z obou "
        "zdrojů se sloučí podle kódu transakce. Spárovaný pohyb má zápis v deníku."
    ),
    columns=(
        Column("id", description="Neměnný identifikátor `BPRRRR-NNNN`."),
        Column("datum", ColumnKind.DATE, "Datum zaúčtování v bance."),
        Column("smer", description="`příjem` nebo `výdaj`."),
        Column("castka", ColumnKind.MONEY, "Částka, vždy kladná."),
        Column("protiucet", description="Účet protistrany (číslo/kód banky)."),
        Column("protiucet_nazev", description="Název protistrany, jak ho uvádí banka."),
        Column("vs", description="Variabilní symbol."),
        Column("ks", description="Konstantní symbol."),
        Column("ss", description="Specifický symbol."),
        Column("zprava", description="Zpráva pro příjemce."),
        Column("popis", description="Typ pohybu podle banky, např. `Platba Cvakem`."),
        Column("kod_transakce", description="Kód transakce v bance; slouží ke sloučení duplicit."),
        Column("zdroj", description="`notifikace`, `výpis` nebo `notifikace, výpis`."),
        Column(
            "parovani",
            description="Spárovaná faktura nebo přijatý doklad; u jiného zápisu prázdné.",
        ),
        Column("stav", description="`nespárováno`, `spárováno` nebo `ignorováno`."),
        Column("denik_id", description="Zápisy v deníku vytvořené z pohybu (oddělené čárkou)."),
        Column("poznamka", description="Volná poznámka, u ignorovaného pohybu důvod."),
    ),
)


class BankError(ValueError):
    """User-facing error (Czech message)."""


@dataclass(frozen=True)
class Candidate:
    kind: str  # "faktura" | "doklad"
    target: str  # invoice number or document id
    label: str
    amount: Decimal
    exact: bool  # VS and amount match -> safe to match automatically
    note: str = ""
    attach_code: bool = False  # document already paid by card: only add the code


def _seq(movement_id: str) -> int:
    m = re.match(r"^BP\d{4}-(\d+)$", movement_id)
    return int(m.group(1)) if m else 0


def year_of(movement_id: str) -> int | None:
    m = re.match(r"^BP(\d{4})-\d+$", movement_id)
    return int(m.group(1)) if m else None


def _same_account(a: str, b: str) -> bool:
    try:
        return str(parse_cz_account(a)) == str(parse_cz_account(b))
    except AccountError:
        return a.replace(" ", "") == b.replace(" ", "")


class BankBook:
    def __init__(self, storage: Storage, firma: FirmaConfig) -> None:
        self.storage = storage
        self.firma = firma
        self.invoices = InvoiceService(storage, firma)
        self.docs = ReceivedDocs(storage, firma)
        self.journal = Journal(storage, firma)

    def table(self, year: int) -> CsvTable:
        return self.storage.table(BANKA_SCHEMA, year)

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
                and (p / BANKA_SCHEMA.name).exists()
            ),
            reverse=True,
        )

    def all(self) -> list[Record]:
        out: list[Record] = []
        for y in self.years():
            out.extend(self.table(y).all())
        return out

    def get(self, movement_id: str) -> Record:
        year = year_of(movement_id)
        rec = self.table(year).get(movement_id) if year else None
        if rec is None:
            raise BankError("Pohyb neexistuje.")
        return rec

    def open_movements(self) -> list[Record]:
        return [m for m in self.all() if m["stav"] == MatchState.OPEN]

    # -- import ------------------------------------------------------------------

    def _find_code(self, code: str, year: int) -> Record | None:
        for y in (year, year - 1, year + 1):
            for r in self.table(y).all() if (self.storage.data_dir / str(y)).exists() else []:
                if r["kod_transakce"] == code:
                    return r
        return None

    def import_movement(self, mv: BankMovement) -> tuple[Record, bool]:
        """Store a movement; returns (record, created). Duplicates are merged by code."""
        own = self.firma.banka.ucet
        if not own or not _same_account(mv.ucet, own):
            raise BankError(
                f"Pohyb patří k jinému účtu ({mv.ucet}) než podnikatelský účet v nastavení."
            )
        year = mv.datum.year
        with file_lock(self.storage.data_dir / str(year) / "banka-import"):
            existing = self._find_code(mv.kod_transakce, year)
            if existing is not None:
                if mv.zdroj is Source.STATEMENT and Source.STATEMENT.value not in existing["zdroj"]:
                    # The statement is the source of truth: it completes the notification.
                    changes: Record = {"zdroj": f"{existing['zdroj']}, {Source.STATEMENT.value}"}
                    for key in ("protiucet", "protiucet_nazev", "vs", "ks", "ss", "zprava"):
                        value = getattr(mv, key)
                        if value and not existing[key]:
                            changes[key] = value
                    existing = self.table(year_of(existing["id"]) or year).update(
                        existing["id"], changes
                    )
                return existing, False
            record = self.table(year).insert(
                lambda rows: {
                    "id": f"BP{year}-{max((_seq(r['id']) for r in rows), default=0) + 1:04d}",
                    "datum": mv.datum,
                    "smer": mv.smer.value,
                    "castka": mv.castka,
                    "protiucet": mv.protiucet,
                    "protiucet_nazev": mv.protiucet_nazev,
                    "vs": mv.vs,
                    "ks": mv.ks,
                    "ss": mv.ss,
                    "zprava": mv.zprava,
                    "popis": mv.popis,
                    "kod_transakce": mv.kod_transakce,
                    "zdroj": mv.zdroj.value,
                    "parovani": "",
                    "stav": MatchState.OPEN.value,
                    "denik_id": "",
                    "poznamka": "",
                }
            )
        return record, True

    # -- candidates ----------------------------------------------------------------

    def candidates(self, m: Record) -> list[Candidate]:
        out: list[Candidate] = []
        amount: Decimal = m["castka"]
        vs = m["vs"].lstrip("0")
        if m["smer"] == Direction.IN:
            for inv in self.invoices.all_invoices():
                if inv["stav"] not in OPEN_STATES:
                    continue
                rest = self.invoices.remaining(inv)
                vs_ok = bool(vs) and inv["vs"].lstrip("0") == vs
                if vs_ok:
                    if amount == rest:
                        note = ""
                    elif amount < rest:
                        note = f"částečná úhrada, zbývá {rest - amount} Kč"
                    else:
                        note = f"přeplatek {amount - rest} Kč"
                    out.append(
                        Candidate(
                            "faktura",
                            inv["cislo"],
                            self._invoice_label(inv),
                            rest,
                            exact=amount == rest,
                            note=note,
                        )
                    )
                elif amount == rest:
                    out.append(
                        Candidate(
                            "faktura",
                            inv["cislo"],
                            self._invoice_label(inv),
                            rest,
                            exact=False,
                            note="sedí jen částka",
                        )
                    )
        else:
            for d in self.docs.all():
                if d["stav"] == DocState.CONFIRMED and d["castka"]:
                    vs_ok = bool(vs) and d["vs"].lstrip("0") == vs
                    acc_ok = (
                        bool(m["protiucet"])
                        and bool(d["ucet"])
                        and _same_account(m["protiucet"], d["ucet"])
                    )
                    if d["castka"] == amount and (vs_ok or acc_ok):
                        out.append(
                            Candidate(
                                "doklad",
                                d["id"],
                                self._doc_label(d),
                                amount,
                                exact=vs_ok,
                                note="" if vs_ok else "sedí účet a částka",
                            )
                        )
                    elif d["castka"] == amount:
                        out.append(
                            Candidate(
                                "doklad",
                                d["id"],
                                self._doc_label(d),
                                amount,
                                exact=False,
                                note="sedí jen částka",
                            )
                        )
                elif d["stav"] == DocState.PAID and d["castka"] == amount and d["datum_uhrady"]:
                    rows = self.journal.for_document(d["id"])
                    no_code = any(
                        r["ucet"] == Account.BANK and r["cislo_dokladu"] == d["id"] for r in rows
                    )
                    near = abs((m["datum"] - d["datum_uhrady"]).days) <= CARD_DAYS
                    if no_code and near:
                        out.append(
                            Candidate(
                                "doklad",
                                d["id"],
                                self._doc_label(d),
                                amount,
                                exact=False,
                                attach_code=True,
                                note="už zaplaceno kartou, doplní se kód transakce",
                            )
                        )
        out.sort(key=lambda c: (not c.exact, c.note != "", c.target))
        return out

    def _invoice_label(self, inv: Record) -> str:
        view = self.invoices.view(inv["cislo"])
        name = view.customer.get("nazev", "") if view else ""
        return f"Faktura {inv['cislo']} – {name}"

    @staticmethod
    def _doc_label(d: Record) -> str:
        return f"{d['id']} – {d['dodavatel_nazev']}" + (f" ({d['popis']})" if d["popis"] else "")

    def auto_match(self, m: Record) -> Record:
        """Match only when exactly one candidate has the same VS and amount."""
        if m["stav"] != MatchState.OPEN:
            return m
        exact = [c for c in self.candidates(m) if c.exact]
        if len(exact) == 1:
            return self.match(m["id"], exact[0].kind, exact[0].target)
        return m

    # -- actions -------------------------------------------------------------------

    def _done(self, m: Record, target: str, journal_ids: list[str], note: str = "") -> Record:
        return self.table(year_of(m["id"]) or 0).update(
            m["id"],
            {
                "stav": MatchState.MATCHED.value,
                "parovani": target,
                "denik_id": ",".join(journal_ids),
                "poznamka": note,
            },
        )

    def _require_open(self, movement_id: str) -> Record:
        m = self.get(movement_id)
        if m["stav"] != MatchState.OPEN:
            raise BankError("Pohyb už je zpracovaný.")
        return m

    def match(self, movement_id: str, kind: str, target: str) -> Record:
        m = self._require_open(movement_id)
        code = m["kod_transakce"]
        before = {r["id"] for r in self.journal.for_document(target)}
        try:
            if kind == "faktura":
                if m["smer"] != Direction.IN:
                    raise BankError("Fakturu lze spárovat jen s příchozí platbou.")
                self.invoices.mark_paid(
                    target,
                    m["datum"],
                    method=PaymentMethod.TRANSFER,
                    kod_transakce=code,
                    amount=m["castka"],
                )
            elif kind == "doklad":
                if m["smer"] != Direction.OUT:
                    raise BankError("Přijatý doklad lze spárovat jen s odchozí platbou.")
                doc = self.docs.require(target)
                if doc["stav"] == DocState.PAID:
                    # Paid by card earlier: the existing cash book row only gets the code.
                    rows = [
                        r for r in self.journal.for_document(target) if r["ucet"] == Account.BANK
                    ]
                    if not rows:
                        raise BankError("Doklad byl zaplacen jinak než z účtu.")
                    self.journal.set_number(rows[0]["id"], code)
                    return self._done(m, target, [rows[0]["id"]], note=ATTACHED_NOTE)
                if doc["castka"] != m["castka"]:
                    raise BankError(
                        "Částka dokladu se liší od platby. Opravte doklad nebo zapište pohyb jinak."
                    )
                method = (
                    PaymentMethod.CARD if "kart" in m["popis"].lower() else PaymentMethod.TRANSFER
                )
                self.docs.pay(target, m["datum"], method, code)
            else:
                raise BankError("Neznámý typ párování.")
        except (InvoiceError, ReceivedError, JournalError) as exc:
            raise BankError(str(exc)) from exc
        new = [r["id"] for r in self.journal.for_document(target) if r["id"] not in before]
        return self._done(m, target, new)

    def book_other(
        self, movement_id: str, kategorie: int, popis: str, zakazka_id: str = ""
    ) -> Record:
        """Write a movement without a document (pojistné, poplatek, vklad…) into the cash book."""
        m = self._require_open(movement_id)
        try:
            row = self.journal.add(
                EntryDraft(
                    datum=m["datum"],
                    ucet=Account.BANK,
                    smer=m["smer"],
                    castka=m["castka"],
                    kategorie=kategorie,
                    popis=popis or m["popis"] or m["zprava"],
                    zpusob_uhrady=PaymentMethod.CARD
                    if "kart" in m["popis"].lower()
                    else PaymentMethod.TRANSFER,
                    zakazka_id=zakazka_id,
                    kod_transakce=m["kod_transakce"],
                )
            )
        except JournalError as exc:
            raise BankError(str(exc)) from exc
        return self._done(m, "", [row["id"]])

    def book_transfer(self, movement_id: str, popis: str = "") -> Record:
        """Cash deposited to / withdrawn from the account (průběžné položky)."""
        m = self._require_open(movement_id)
        to_bank = m["smer"] == Direction.IN
        text = popis or ("Vklad hotovosti na účet" if to_bank else "Výběr z účtu do pokladny")
        try:
            out, inn = self.journal.transfer(
                m["datum"],
                Account.CASH if to_bank else Account.BANK,
                Account.BANK if to_bank else Account.CASH,
                m["castka"],
                text,
                m["kod_transakce"],
            )
        except JournalError as exc:
            raise BankError(str(exc)) from exc
        return self._done(m, "", [out["id"], inn["id"]])

    def ignore(self, movement_id: str, reason: str) -> Record:
        m = self._require_open(movement_id)
        if not reason.strip():
            raise BankError("Uveďte důvod, proč pohyb do deníku nepatří.")
        return self.table(year_of(m["id"]) or 0).update(
            m["id"], {"stav": MatchState.IGNORED.value, "poznamka": reason.strip()}
        )

    def unmatch(self, movement_id: str) -> Record:
        """Undo a match: cash book rows created from the movement are removed."""
        m = self.get(movement_id)
        if m["stav"] == MatchState.OPEN:
            return m
        target = m["parovani"]
        if m["stav"] == MatchState.MATCHED:
            if target and self.invoices.get(target) is not None:
                self.invoices.mark_unpaid(target)
            elif target and self.docs.get(target) is not None:
                if m["poznamka"] == ATTACHED_NOTE:
                    # Only the code was attached: give the row its document number back.
                    for entry_id in filter(None, m["denik_id"].split(",")):
                        self.journal.set_number(entry_id, target)
                else:
                    self.docs.unpay(target)
            else:
                for entry_id in filter(None, m["denik_id"].split(",")):
                    self.journal.delete(entry_id)
        return self.table(year_of(m["id"]) or 0).update(
            m["id"], {"stav": MatchState.OPEN.value, "parovani": "", "denik_id": "", "poznamka": ""}
        )


__all__ = ["BANKA_SCHEMA", "BankBook", "BankError", "Candidate", "MatchState"]
