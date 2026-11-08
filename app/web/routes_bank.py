"""Bank movements and payment matching; mail fetching status."""

from __future__ import annotations

import email
import logging
from email import policy
from email.message import EmailMessage
from typing import Any

from fastapi import APIRouter, Depends, Request
from starlette.datastructures import UploadFile
from starlette.responses import RedirectResponse, Response

from app.banks import parser_for_email
from app.banks.book import BankBook, BankError, MatchState
from app.config import FirmaConfig
from app.jobs import ZAKAZKY_SCHEMA
from app.mail.fetch import MailProcessor
from app.mail.imap import imap_configured
from app.mail.scheduler import fetch_now
from app.tax.categories import EXPENSE_COLUMNS, INCOME_COLUMNS
from app.web.security import verify_csrf
from app.web.templating import render

log = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(verify_csrf)])


def _book(request: Request) -> BankBook:
    firma = FirmaConfig.load(request.app.state.settings.firma_path)
    return BankBook(request.app.state.storage, firma)


def _page(request: Request, status_code: int = 200, **ctx: Any) -> Response:
    book = _book(request)
    filtr = ctx.pop("filtr", request.query_params.get("filtr", ""))
    rows = book.all()
    open_rows = [m for m in rows if m["stav"] == MatchState.OPEN]
    shown = open_rows if filtr != "vse" else rows
    shown.sort(key=lambda m: (m["datum"], m["id"]), reverse=True)
    items = [
        {"m": m, "candidates": book.candidates(m) if m["stav"] == MatchState.OPEN else []}
        for m in shown
    ]
    jobs = request.app.state.storage.table(ZAKAZKY_SCHEMA).all()
    jobs.sort(key=lambda j: j["id"], reverse=True)
    return render(
        request,
        "banka/seznam.html",
        status_code=status_code,
        items=items,
        open_count=len(open_rows),
        filtr=filtr,
        incomes=INCOME_COLUMNS,
        expenses=EXPENSE_COLUMNS,
        jobs=jobs,
        journal_ready=book.journal.ready,
        own_account=book.firma.banka.ucet,
        **ctx,
    )


@router.get("/banka")
def bank_list(request: Request) -> Response:
    return _page(request)


def _done(movement_id: str) -> RedirectResponse:
    return RedirectResponse(f"/banka#{movement_id}", status_code=303)


async def _action(request: Request, movement_id: str, action: str) -> Response:
    form = await request.form()
    book = _book(request)
    try:
        if action == "parovat":
            target = str(form.get("cil", ""))
            kind, _, target_id = target.partition(":")
            book.match(movement_id, kind, target_id)
        elif action == "zapsat":
            try:
                column = int(str(form.get("kategorie", "")))
            except ValueError as exc:
                raise BankError("Vyberte kategorii.") from exc
            book.book_other(
                movement_id,
                column,
                str(form.get("popis", "")).strip(),
                str(form.get("zakazka_id", "")),
            )
        elif action == "prevod":
            book.book_transfer(movement_id, str(form.get("popis", "")).strip())
        elif action == "ignorovat":
            book.ignore(movement_id, str(form.get("duvod", "")))
        elif action == "zrusit":
            book.unmatch(movement_id)
    except BankError as exc:
        return _page(request, status_code=400, errors=[f"{movement_id}: {exc}"])
    return _done(movement_id)


@router.post("/banka/{movement_id}/parovat")
async def bank_match(request: Request, movement_id: str) -> Response:
    return await _action(request, movement_id, "parovat")


@router.post("/banka/{movement_id}/zapsat")
async def bank_book_other(request: Request, movement_id: str) -> Response:
    return await _action(request, movement_id, "zapsat")


@router.post("/banka/{movement_id}/prevod")
async def bank_transfer(request: Request, movement_id: str) -> Response:
    return await _action(request, movement_id, "prevod")


@router.post("/banka/{movement_id}/ignorovat")
async def bank_ignore(request: Request, movement_id: str) -> Response:
    return await _action(request, movement_id, "ignorovat")


@router.post("/banka/{movement_id}/zrusit")
async def bank_unmatch(request: Request, movement_id: str) -> Response:
    return await _action(request, movement_id, "zrusit")


@router.post("/banka/nahrat")
async def bank_upload(request: Request) -> Response:
    """Import notification e-mails saved as .eml (before IMAP is set up, or as a fallback)."""
    form = await request.form()
    files = [f for f in form.getlist("soubory") if isinstance(f, UploadFile) and f.filename]
    book = _book(request)
    errors: list[str] = []
    imported = matched = 0
    for f in files[:50]:
        data = await f.read(1024 * 1024 + 1)
        name = (f.filename or "soubor")[:80]
        msg = email.message_from_bytes(data, policy=policy.default)
        parser = parser_for_email(msg) if isinstance(msg, EmailMessage) else None
        movement = parser.parse_email(msg) if parser and isinstance(msg, EmailMessage) else None
        if movement is None:
            errors.append(f"{name}: není to notifikace podporované banky.")
            continue
        try:
            record, created = book.import_movement(movement)
        except BankError as exc:
            errors.append(f"{name}: {exc}")
            continue
        imported += int(created)
        if book.auto_match(record)["stav"] == MatchState.MATCHED:
            matched += 1
    info = f"Načteno pohybů: {imported}, automaticky spárováno: {matched}."
    if errors:
        return _page(request, status_code=400, errors=errors, info=info)
    return _page(request, info=info)


# -- mail ---------------------------------------------------------------------------


@router.get("/posta")
def mail_status(request: Request) -> Response:
    settings = request.app.state.settings
    firma = FirmaConfig.load(settings.firma_path)
    state = MailProcessor(request.app.state.storage, firma, settings).state()
    return render(
        request,
        "banka/posta.html",
        s=settings,
        configured=imap_configured(settings),
        last=state.get("posledni_beh"),
        seen=len(state.get("videne", [])),
    )


@router.post("/posta/stahnout")
def mail_fetch(request: Request) -> Response:
    settings = request.app.state.settings
    if not imap_configured(settings):
        return RedirectResponse("/posta", status_code=303)
    result = fetch_now(settings, request.app.state.storage, request.app.state.mailbox_factory)
    log.info("Manual mail fetch finished")
    if result.errors:
        return RedirectResponse("/posta?chyba=1", status_code=303)
    return RedirectResponse("/posta?hotovo=1", status_code=303)
