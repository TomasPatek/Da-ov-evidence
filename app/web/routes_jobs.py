"""Jobs (zakázky): list with warnings, create, detail with invoices and totals, edit."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import RedirectResponse, Response

from app.config import FirmaConfig
from app.contacts import KONTAKTY_SCHEMA
from app.invoices.schemas import InvoiceState
from app.invoices.service import InvoiceService
from app.jobs import ZAKAZKY_SCHEMA, JobState, new_job_id
from app.money import ZERO, sum_money
from app.storage import CsvTable, Record
from app.web.forms import parse_date
from app.web.routes_contacts import contact_choices
from app.web.security import verify_csrf
from app.web.templating import render

router = APIRouter(prefix="/zakazky", dependencies=[Depends(verify_csrf)])


def _table(request: Request) -> CsvTable:
    return request.app.state.storage.table(ZAKAZKY_SCHEMA)  # type: ignore[no-any-return]


def _invoices(request: Request) -> InvoiceService:
    firma = FirmaConfig.load(request.app.state.settings.firma_path)
    return InvoiceService(request.app.state.storage, firma)


def job_warnings(job: Record, invoices: list[Record]) -> list[str]:
    active = [i for i in invoices if i["stav"] != InvoiceState.CANCELLED]
    warnings = []
    if job["stav"] == JobState.DONE and not active:
        warnings.append("Zakázka je dokončená, ale nemá fakturu.")
    return warnings


def job_totals(invoices: list[Record]) -> dict[str, Any]:
    active = [i for i in invoices if i["stav"] != InvoiceState.CANCELLED]
    paid = [i for i in active if i["stav"] == InvoiceState.PAID]
    return {
        "fakturovano": sum_money(i["castka"] for i in active),
        "uhrazeno": sum_money(i["castka"] for i in paid),
        "naklady": ZERO,  # direct costs arrive with received documents (phase 2)
    }


async def _form(request: Request) -> dict[str, str]:
    data = await request.form()
    return {k: v for k, v in data.items() if isinstance(v, str)}


def _from_form(request: Request, form: dict[str, str]) -> tuple[Record, list[str]]:
    errors: list[str] = []
    rec: Record = {
        "kontakt_id": form.get("kontakt_id", "").strip(),
        "nazev": form.get("nazev", "").strip(),
        "adresa_realizace": form.get("adresa_realizace", "").strip(),
        "stav": form.get("stav", JobState.INQUIRY.value),
        "poznamka": form.get("poznamka", "").strip(),
    }
    if request.app.state.storage.table(KONTAKTY_SCHEMA).get(rec["kontakt_id"]) is None:
        errors.append("Vyberte zákazníka.")
    if not rec["nazev"]:
        errors.append("Vyplňte název zakázky.")
    if rec["stav"] not in {s.value for s in JobState}:
        errors.append("Neznámý stav zakázky.")
    rec["datum_zalozeni"] = parse_date(form.get("datum_zalozeni", ""), "datum založení", errors)
    rec["datum_dokonceni"] = parse_date(
        form.get("datum_dokonceni", ""), "datum dokončení", errors, required=False
    )
    if (
        rec["stav"] in (JobState.DONE, JobState.INVOICED, JobState.PAID)
        and not rec["datum_dokonceni"]
    ):
        rec["datum_dokonceni"] = date.today()
    if (
        rec["datum_zalozeni"]
        and rec["datum_dokonceni"]
        and rec["datum_dokonceni"] < rec["datum_zalozeni"]
    ):
        errors.append("Datum dokončení nesmí být dřív než datum založení.")
    return rec, errors


@router.get("")
def job_list(request: Request, stav: str = "") -> Response:
    jobs = _table(request).all()
    invoices = _invoices(request).all_invoices()
    contacts = {c["id"]: c for c in request.app.state.storage.table(KONTAKTY_SCHEMA).all()}
    if stav:
        jobs = [j for j in jobs if j["stav"] == stav]
    jobs.sort(key=lambda j: j["id"], reverse=True)
    rows = []
    for j in jobs:
        inv = [i for i in invoices if i["zakazka_id"] == j["id"]]
        rows.append(
            {"job": j, "contact": contacts.get(j["kontakt_id"]), "warnings": job_warnings(j, inv)}
        )
    return render(request, "zakazky/seznam.html", rows=rows, stav=stav, states=JobState)


@router.get("/nova")
def job_new(request: Request, kontakt: str = "") -> Response:
    rec: Record = {
        "kontakt_id": kontakt,
        "nazev": "",
        "adresa_realizace": "",
        "stav": JobState.INQUIRY.value,
        "datum_zalozeni": date.today(),
        "datum_dokonceni": None,
        "poznamka": "",
    }
    contact = request.app.state.storage.table(KONTAKTY_SCHEMA).get(kontakt)
    if contact and contact["ulice"]:
        rec["adresa_realizace"] = f"{contact['ulice']}, {contact['mesto']}"
    return render(
        request, "zakazky/nova.html", j=rec, contacts=contact_choices(request), states=JobState
    )


@router.post("/nova")
async def job_create(request: Request) -> Response:
    form = await _form(request)
    rec, errors = _from_form(request, form)
    if errors:
        return render(
            request,
            "zakazky/nova.html",
            status_code=400,
            j=rec,
            contacts=contact_choices(request),
            states=JobState,
            errors=errors,
        )
    year = rec["datum_zalozeni"].year
    new = _table(request).insert(lambda rows: {"id": new_job_id(rows, year), **rec})
    return RedirectResponse(f"/zakazky/{new['id']}", status_code=303)


def _get(request: Request, job_id: str) -> Record:
    rec = _table(request).get(job_id)
    if rec is None:
        raise HTTPException(404, "Zakázka neexistuje.")
    return rec


def _detail(request: Request, job: Record, status_code: int = 200, **ctx: Any) -> Response:
    invoices = _invoices(request).job_invoices(job["id"])
    invoices.sort(key=lambda i: i["cislo"])
    contact = request.app.state.storage.table(KONTAKTY_SCHEMA).get(job["kontakt_id"])
    return render(
        request,
        "zakazky/detail.html",
        status_code=status_code,
        j=job,
        contact=contact,
        contacts=contact_choices(request),
        states=JobState,
        invoices=invoices,
        totals=job_totals(invoices),
        warnings=job_warnings(job, invoices),
        **ctx,
    )


@router.get("/{job_id}")
def job_detail(request: Request, job_id: str) -> Response:
    return _detail(request, _get(request, job_id))


@router.post("/{job_id}")
async def job_save(request: Request, job_id: str) -> Response:
    old = _get(request, job_id)
    form = await _form(request)
    rec, errors = _from_form(request, form)
    if rec["kontakt_id"] != old["kontakt_id"] and _invoices(request).job_invoices(job_id):
        errors.append("Zákazníka nejde změnit, zakázka už má faktury.")
    if errors:
        return _detail(request, {**old, **rec}, status_code=400, errors=errors)
    _table(request).update(job_id, rec)
    return RedirectResponse(f"/zakazky/{job_id}?ulozeno=1", status_code=303)
