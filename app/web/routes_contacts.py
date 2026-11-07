"""Contacts: list, create (optionally from ARES), edit, refresh from ARES, delete."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import RedirectResponse, Response

from app.ares.client import AresSubjekt, AresUnavailable
from app.ares.ico import normalize_ico, validate_ico
from app.config import FirmaConfig
from app.contacts import KONTAKTY_SCHEMA, ContactType, new_contact_id
from app.invoices.service import InvoiceService
from app.jobs import ZAKAZKY_SCHEMA
from app.storage import CsvTable, Record
from app.web.forms import DIC_RE, EMAIL_RE, PSC_RE
from app.web.security import verify_csrf
from app.web.templating import render

router = APIRouter(prefix="/kontakty", dependencies=[Depends(verify_csrf)])

FIELDS = ("typ", "ico", "dic", "nazev", "ulice", "mesto", "psc", "email", "telefon", "poznamka")


def _table(request: Request) -> CsvTable:
    return request.app.state.storage.table(KONTAKTY_SCHEMA)  # type: ignore[no-any-return]


def _empty() -> Record:
    rec: Record = dict.fromkeys(FIELDS, "")
    rec["typ"] = ContactType.CUSTOMER.value
    rec["ares_aktualizovano"] = None
    return rec


def _from_form(form: dict[str, str]) -> tuple[Record, list[str]]:
    rec: Record = {k: form.get(k, "").strip() for k in FIELDS}
    rec["dic"] = rec["dic"].replace(" ", "").upper()
    errors = []
    if rec["typ"] not in {t.value for t in ContactType}:
        errors.append("Vyberte typ kontaktu.")
    if not rec["nazev"]:
        errors.append("Vyplňte název nebo jméno.")
    if rec["ico"]:
        if validate_ico(rec["ico"]):
            rec["ico"] = normalize_ico(rec["ico"])
        else:
            errors.append("IČO nemá platný kontrolní součet.")
    if rec["dic"] and not DIC_RE.match(rec["dic"]):
        errors.append("DIČ zadejte ve tvaru CZ12345678.")
    if rec["psc"] and not PSC_RE.match(rec["psc"]):
        errors.append("PSČ zadejte jako pět číslic.")
    if rec["email"] and not EMAIL_RE.match(rec["email"]):
        errors.append("E-mail nemá správný tvar.")
    return rec, errors


async def _form(request: Request) -> dict[str, str]:
    data = await request.form()
    return {k: v for k, v in data.items() if isinstance(v, str)}


def _apply_ares(rec: Record, subj: AresSubjekt) -> Record:
    return {
        **rec,
        "ico": subj.ico,
        "nazev": subj.nazev,
        "dic": subj.dic,
        "ulice": subj.ulice,
        "mesto": subj.mesto,
        "psc": subj.psc,
        "ares_aktualizovano": date.today(),
    }


def _ares_lookup(request: Request, ico: str) -> tuple[AresSubjekt | None, str | None]:
    if not validate_ico(ico):
        return None, "IČO nemá platný kontrolní součet."
    try:
        subj = request.app.state.ares.lookup(ico)
    except AresUnavailable:
        return None, "ARES je teď nedostupný. Údaje vyplňte ručně."
    if subj is None:
        return None, "Subjekt s tímto IČO v ARES neexistuje."
    return subj, None


def _duplicate(request: Request, ico: str, own_id: str = "") -> Record | None:
    if not ico:
        return None
    for r in _table(request).all():
        if r["ico"] == ico and r["id"] != own_id:
            return r
    return None


@router.get("")
def contact_list(request: Request, q: str = "", typ: str = "") -> Response:
    rows = _table(request).all()
    if typ:
        rows = [r for r in rows if r["typ"] in (typ, ContactType.BOTH)]
    if q:
        needle = q.strip().casefold()
        rows = [
            r
            for r in rows
            if needle in r["nazev"].casefold()
            or needle in r["ico"]
            or needle in r["email"].casefold()
        ]
    rows.sort(key=lambda r: r["nazev"].casefold())
    return render(request, "kontakty/seznam.html", rows=rows, q=q, typ=typ, types=ContactType)


@router.get("/novy")
def contact_new(request: Request, typ: str = "") -> Response:
    rec = _empty()
    if typ in {t.value for t in ContactType}:
        rec["typ"] = typ
    return render(request, "kontakty/novy.html", c=rec, types=ContactType)


@router.get("/ares")
def contact_ares(request: Request, ico: str = "", id: str = "") -> Response:
    """HTMX: contact fields pre-filled from ARES."""
    form = dict(request.query_params)
    rec, _ = _from_form(form)
    rec["ares_aktualizovano"] = None
    subj, error = _ares_lookup(request, ico)
    ctx: dict[str, Any] = {"c": rec, "types": ContactType}
    if subj is None:
        ctx["errors"] = [error]
    else:
        ctx["c"] = _apply_ares(rec, subj)
        dup = _duplicate(request, subj.ico, id)
        ctx["info"] = "Údaje načteny z ARES."
        if dup:
            ctx["warning"] = dup
    return render(request, "kontakty/_pole.html", **ctx)


@router.post("/novy")
async def contact_create(request: Request) -> Response:
    form = await _form(request)
    rec, errors = _from_form(form)
    rec["ares_aktualizovano"] = (
        date.fromisoformat(form["ares_aktualizovano"]) if form.get("ares_aktualizovano") else None
    )
    dup = _duplicate(request, rec["ico"])
    if dup and not form.get("i_tak"):
        errors.append(f"Kontakt s tímto IČO už existuje: {dup['nazev']}.")
    if errors:
        return render(
            request,
            "kontakty/novy.html",
            status_code=400,
            c=rec,
            types=ContactType,
            errors=errors,
        )
    new = _table(request).insert(lambda rows: {"id": new_contact_id(rows), **rec})
    target = form.get("dal", "")
    if target == "zakazka":
        return RedirectResponse(f"/zakazky/nova?kontakt={new['id']}", status_code=303)
    if target == "faktura":
        return RedirectResponse(f"/faktury/nova?kontakt={new['id']}", status_code=303)
    return RedirectResponse(f"/kontakty/{new['id']}", status_code=303)


def _get(request: Request, contact_id: str) -> Record:
    rec = _table(request).get(contact_id)
    if rec is None:
        raise HTTPException(404, "Kontakt neexistuje.")
    return rec


def _detail(request: Request, rec: Record, status_code: int = 200, **ctx: Any) -> Response:
    firma = FirmaConfig.load(request.app.state.settings.firma_path)
    invoices = [
        i
        for i in InvoiceService(request.app.state.storage, firma).all_invoices()
        if i["kontakt_id"] == rec["id"]
    ]
    invoices.sort(key=lambda i: i["cislo"], reverse=True)
    jobs = [
        j
        for j in request.app.state.storage.table(ZAKAZKY_SCHEMA).all()
        if j["kontakt_id"] == rec["id"]
    ]
    jobs.sort(key=lambda j: j["id"], reverse=True)
    return render(
        request,
        "kontakty/detail.html",
        status_code=status_code,
        c=rec,
        types=ContactType,
        invoices=invoices,
        jobs=jobs,
        **ctx,
    )


@router.get("/{contact_id}")
def contact_detail(request: Request, contact_id: str) -> Response:
    return _detail(request, _get(request, contact_id))


@router.post("/{contact_id}")
async def contact_save(request: Request, contact_id: str) -> Response:
    old = _get(request, contact_id)
    form = await _form(request)
    rec, errors = _from_form(form)
    if errors:
        return _detail(request, {**old, **rec}, status_code=400, errors=errors)
    _table(request).update(contact_id, rec)
    return RedirectResponse(f"/kontakty/{contact_id}?ulozeno=1", status_code=303)


@router.post("/{contact_id}/ares")
def contact_refresh(request: Request, contact_id: str) -> Response:
    rec = _get(request, contact_id)
    subj, error = _ares_lookup(request, rec["ico"])
    if subj is None:
        return _detail(request, rec, status_code=400, errors=[error])
    updated = _table(request).update(contact_id, _apply_ares(rec, subj))
    return _detail(request, updated, info="Údaje aktualizovány z ARES.")


@router.post("/{contact_id}/smazat")
def contact_delete(request: Request, contact_id: str) -> Response:
    rec = _get(request, contact_id)
    firma = FirmaConfig.load(request.app.state.settings.firma_path)
    used = any(
        i["kontakt_id"] == contact_id
        for i in InvoiceService(request.app.state.storage, firma).all_invoices()
    ) or any(
        j["kontakt_id"] == contact_id for j in request.app.state.storage.table(ZAKAZKY_SCHEMA).all()
    )
    if used:
        return _detail(
            request,
            rec,
            status_code=400,
            errors=["Kontakt má faktury nebo zakázky, proto ho nejde smazat."],
        )
    _table(request).delete(contact_id)
    return RedirectResponse("/kontakty", status_code=303)


def contact_choices(request: Request) -> list[Record]:
    rows = _table(request).all()
    rows.sort(key=lambda r: r["nazev"].casefold())
    return rows
