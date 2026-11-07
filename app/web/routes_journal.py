"""Cash book: entries, manual entry, cash/bank transfer, ET 328 table."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Request
from starlette.responses import RedirectResponse, Response

from app.config import FirmaConfig
from app.jobs import ZAKAZKY_SCHEMA
from app.journal import (
    TRANSIT_EXPENSE,
    TRANSIT_INCOME,
    Account,
    EntryDraft,
    Journal,
    JournalError,
    PaymentMethod,
)
from app.money import parse_user_amount
from app.tax.categories import EXPENSE_COLUMNS, INCOME_COLUMNS, category
from app.web.forms import parse_date
from app.web.security import verify_csrf
from app.web.templating import render

router = APIRouter(prefix="/denik", dependencies=[Depends(verify_csrf)])

MONTHS = (
    "leden",
    "únor",
    "březen",
    "duben",
    "květen",
    "červen",
    "červenec",
    "srpen",
    "září",
    "říjen",
    "listopad",
    "prosinec",
)


def _journal(request: Request) -> Journal:
    firma = FirmaConfig.load(request.app.state.settings.firma_path)
    return Journal(request.app.state.storage, firma)


def _year(journal: Journal, rok: str) -> int:
    if rok.isdigit():
        return int(rok)
    years = journal.years()
    today = date.today().year
    return today if today in years or not years else years[-1]


def column_label(column: int) -> str:
    if column == TRANSIT_INCOME:
        return "6 – průběžné položky (převod)"
    if column == TRANSIT_EXPENSE:
        return "7 – průběžné položky (převod)"
    return f"{column} – {category(column).label}"


@router.get("")
def journal_list(request: Request, rok: str = "", mesic: str = "") -> Response:
    journal = _journal(request)
    if not journal.ready:
        return render(request, "denik/nenastaveno.html")
    year = _year(journal, rok)
    report = journal.et_report(year)
    rows = report.rows
    month = int(mesic) if mesic.isdigit() and 1 <= int(mesic) <= 12 else 0
    if month:
        rows = [r for r in rows if r.entry["datum_uhrady"].month == month]
    return render(
        request,
        "denik/seznam.html",
        report=report,
        rows=list(reversed(rows)),
        year=year,
        years=journal.years(),
        month=month,
        months=MONTHS,
        column_label=column_label,
    )


@router.get("/et328")
def journal_et328(request: Request, rok: str = "") -> Response:
    journal = _journal(request)
    if not journal.ready:
        return render(request, "denik/nenastaveno.html")
    year = _year(journal, rok)
    return render(
        request, "denik/et328.html", report=journal.et_report(year), year=year, months=MONTHS
    )


def _form(request: Request, status_code: int = 200, **ctx: Any) -> Response:
    jobs = request.app.state.storage.table(ZAKAZKY_SCHEMA).all()
    jobs.sort(key=lambda j: j["id"], reverse=True)
    return render(
        request,
        "denik/novy.html",
        status_code=status_code,
        incomes=INCOME_COLUMNS,
        expenses=EXPENSE_COLUMNS,
        methods=[m for m in PaymentMethod if m is not PaymentMethod.CASH],
        jobs=jobs,
        today=date.today(),
        **ctx,
    )


@router.get("/novy")
def entry_new(request: Request, smer: str = "výdaj") -> Response:
    v = {
        "smer": smer if smer in ("příjem", "výdaj") else "výdaj",
        "ucet": "hotovost",
        "datum": date.today().isoformat(),
        "kategorie": "",
        "castka": "",
        "popis": "",
        "zpusob_uhrady": "převod",
        "zakazka_id": "",
        "poznamka": "",
    }
    return _form(request, v=v)


@router.post("/novy")
async def entry_create(request: Request) -> Response:
    form = await request.form()
    v = {
        k: str(form.get(k, "")).strip()
        for k in (
            "smer",
            "ucet",
            "datum",
            "kategorie",
            "castka",
            "popis",
            "zpusob_uhrady",
            "zakazka_id",
            "poznamka",
        )
    }
    errors: list[str] = []
    when = parse_date(v["datum"], "datum úhrady", errors)
    try:
        amount = parse_user_amount(v["castka"])
    except ValueError:
        errors.append("Částka není platné číslo.")
        amount = None
    try:
        column = int(v["kategorie"])
    except ValueError:
        errors.append("Vyberte kategorii.")
        column = 0
    if v["ucet"] not in {a.value for a in Account}:
        errors.append("Vyberte pokladnu nebo účet.")
    if when and when > date.today():
        errors.append("Datum úhrady nesmí být v budoucnosti.")
    if not errors and when and amount is not None:
        account = Account(v["ucet"])
        method = (
            PaymentMethod.CASH
            if account is Account.CASH
            else PaymentMethod(v["zpusob_uhrady"])
            if v["zpusob_uhrady"] in {m.value for m in PaymentMethod}
            else PaymentMethod.TRANSFER
        )
        try:
            _journal(request).add(
                EntryDraft(
                    datum=when,
                    ucet=account,
                    smer=v["smer"],
                    castka=amount,
                    kategorie=column,
                    popis=v["popis"],
                    zpusob_uhrady=method,
                    zakazka_id=v["zakazka_id"],
                    poznamka=v["poznamka"],
                )
            )
        except JournalError as exc:
            errors.append(str(exc))
        else:
            return RedirectResponse(f"/denik?rok={when.year}&ulozeno=1", status_code=303)
    return _form(request, status_code=400, v=v, errors=errors)


@router.get("/prevod")
def transfer_form(request: Request) -> Response:
    return render(
        request,
        "denik/prevod.html",
        v={"datum": date.today().isoformat(), "smer": "do-pokladny", "castka": "", "popis": ""},
        today=date.today(),
    )


@router.post("/prevod")
async def transfer_create(request: Request) -> Response:
    form = await request.form()
    v = {k: str(form.get(k, "")).strip() for k in ("datum", "smer", "castka", "popis")}
    errors: list[str] = []
    when = parse_date(v["datum"], "datum", errors)
    try:
        amount = parse_user_amount(v["castka"])
    except ValueError:
        errors.append("Částka není platné číslo.")
        amount = None
    if when and when > date.today():
        errors.append("Datum nesmí být v budoucnosti.")
    to_cash = v["smer"] == "do-pokladny"
    text = v["popis"] or ("Výběr z účtu do pokladny" if to_cash else "Vklad z pokladny na účet")
    if not errors and when and amount is not None:
        source, target = (Account.BANK, Account.CASH) if to_cash else (Account.CASH, Account.BANK)
        try:
            _journal(request).transfer(when, source, target, amount, text)
        except JournalError as exc:
            errors.append(str(exc))
        else:
            return RedirectResponse(f"/denik?rok={when.year}&ulozeno=1", status_code=303)
    return render(
        request, "denik/prevod.html", status_code=400, v=v, errors=errors, today=date.today()
    )


@router.post("/{entry_id}/smazat")
def entry_delete(request: Request, entry_id: str) -> Response:
    journal = _journal(request)
    year = int(entry_id[1:5]) if entry_id[1:5].isdigit() else date.today().year
    row = next((r for r in journal.entries(year) if r["id"] == entry_id), None)
    if row is None or row["doklad_id"]:
        # Rows created from invoices or documents are removed by cancelling the payment there.
        return RedirectResponse(f"/denik?rok={year}", status_code=303)
    journal.delete(entry_id)
    return RedirectResponse(f"/denik?rok={year}&smazano=1", status_code=303)
