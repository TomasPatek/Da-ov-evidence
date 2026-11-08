"""Cash book: entries, manual entry, cash/bank transfer, ET 328 table."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
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
    attachment_kind,
)
from app.money import parse_user_amount
from app.tax.categories import EXPENSE_COLUMNS, INCOME_COLUMNS, category
from app.web.forms import parse_date, read_upload, safe_return_path
from app.web.security import verify_csrf
from app.web.templating import render

log = logging.getLogger(__name__)
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


@router.get("/kategorie")
def entry_categories(request: Request, smer: str = "výdaj", kategorie: str = "") -> Response:
    """HTMX: category select limited to the chosen direction."""
    return render(
        request,
        "denik/_kategorie.html",
        smer=smer if smer in ("příjem", "výdaj") else "výdaj",
        selected=kategorie,
        incomes=INCOME_COLUMNS,
        expenses=EXPENSE_COLUMNS,
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
        "kod_transakce": "",
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
            "kod_transakce",
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
    photo = await read_upload(form, "priloha", request.app.state.settings.max_upload_bytes, errors)
    if photo is not None:
        try:
            attachment_kind(photo)
        except JournalError as exc:
            errors.append(str(exc))
    if not errors and when and amount is not None:
        account = Account(v["ucet"])
        method = (
            PaymentMethod.CASH
            if account is Account.CASH
            else PaymentMethod(v["zpusob_uhrady"])
            if v["zpusob_uhrady"] in {m.value for m in PaymentMethod}
            else PaymentMethod.TRANSFER
        )
        journal = _journal(request)
        try:
            entry = journal.add(
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
                    kod_transakce=v["kod_transakce"],
                )
            )
            if photo is not None:
                journal.attach(entry["id"], photo)
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
        v={
            "datum": date.today().isoformat(),
            "smer": "do-pokladny",
            "castka": "",
            "popis": "",
            "kod_transakce": "",
        },
        today=date.today(),
    )


@router.post("/prevod")
async def transfer_create(request: Request) -> Response:
    form = await request.form()
    v = {
        k: str(form.get(k, "")).strip()
        for k in ("datum", "smer", "castka", "popis", "kod_transakce")
    }
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
            _journal(request).transfer(when, source, target, amount, text, v["kod_transakce"])
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


# -- photo or scan of the document of an entry ----------------------------------------


@router.get("/{entry_id}/priloha")
def attachment_file(request: Request, entry_id: str) -> Response:
    journal = _journal(request)
    try:
        entry = journal.get(entry_id)
    except JournalError as exc:
        raise HTTPException(404, str(exc)) from exc
    path = journal.attachment_path(entry)
    if path is None:
        raise HTTPException(404, "Zápis nemá přiložený doklad.")
    data = path.read_bytes()
    kind = attachment_kind(data)
    # Photos open in the browser; a PDF is downloaded (nothing from it runs in the app).
    disposition = "inline" if kind.is_image else "attachment"
    return Response(
        data,
        media_type=kind.mime,
        headers={
            "Content-Disposition": f'{disposition}; filename="{entry_id}.{kind.ext}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{entry_id}/priloha")
async def attachment_upload(request: Request, entry_id: str) -> Response:
    form = await request.form()
    back = safe_return_path(str(form.get("zpet", "")), f"/denik?rok={entry_id[1:5]}")
    errors: list[str] = []
    data = await read_upload(form, "priloha", request.app.state.settings.max_upload_bytes, errors)
    if data is None and not errors:
        errors.append("Vyberte fotku nebo PDF dokladu.")
    if data is not None:
        try:
            _journal(request).attach(entry_id, data)
        except JournalError as exc:
            errors.append(str(exc))
    if errors:
        return render(
            request, "denik/priloha-chyba.html", status_code=400, errors=errors, back=back
        )
    log.info("Attachment added to a cash book entry")
    return RedirectResponse(back, status_code=303)


@router.post("/{entry_id}/priloha/smazat")
async def attachment_delete(request: Request, entry_id: str) -> Response:
    form = await request.form()
    back = safe_return_path(str(form.get("zpet", "")), f"/denik?rok={entry_id[1:5]}")
    try:
        _journal(request).remove_attachment(entry_id)
    except JournalError as exc:
        raise HTTPException(404, str(exc)) from exc
    return RedirectResponse(back, status_code=303)
