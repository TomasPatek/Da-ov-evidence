"""Received documents: upload, review queue, manual entry, payment, preview."""

from __future__ import annotations

import io
import logging
from datetime import date
from typing import Any

import pypdfium2 as pdfium
from fastapi import APIRouter, Depends, HTTPException, Request
from PIL import Image
from starlette.datastructures import FormData, UploadFile
from starlette.responses import RedirectResponse, Response

from app.ares.client import AresUnavailable
from app.ares.ico import normalize_ico, validate_ico
from app.config import FirmaConfig
from app.ingest.files import ACCEPT, UploadError
from app.jobs import ZAKAZKY_SCHEMA
from app.journal import Journal, PaymentMethod
from app.money import parse_user_amount
from app.received import (
    Confirmation,
    DocSource,
    DocState,
    DocType,
    ReceivedDocs,
    ReceivedError,
    year_of,
)
from app.storage import Record
from app.tax.categories import EXPENSE_COLUMNS, hints_for_expense
from app.web.forms import parse_date
from app.web.security import verify_csrf
from app.web.templating import render

log = logging.getLogger(__name__)
router = APIRouter(prefix="/doklady", dependencies=[Depends(verify_csrf)])

PREVIEW_SCALE = 1.4
MAX_FILES = 20


def _docs(request: Request) -> ReceivedDocs:
    firma = FirmaConfig.load(request.app.state.settings.firma_path)
    return ReceivedDocs(request.app.state.storage, firma)


def _jobs(request: Request, current: str = "") -> list[Record]:
    # Costs can arrive after invoicing too (that is what the job warning is for).
    jobs = [
        j
        for j in request.app.state.storage.table(ZAKAZKY_SCHEMA).all()
        if j["stav"] != "uhrazeno" or j["id"] == current
    ]
    jobs.sort(key=lambda j: j["id"], reverse=True)
    return jobs


# -- list and upload ------------------------------------------------------------


@router.get("")
def doc_list(request: Request, filtr: str = "", rok: str = "") -> Response:
    docs = _docs(request)
    rows = docs.all()
    queue = [d for d in rows if d["stav"] == DocState.REVIEW]
    unpaid = [d for d in rows if d["stav"] == DocState.CONFIRMED]
    if filtr == "kontrola":
        shown = queue
    elif filtr == "neuhrazene":
        shown = unpaid
    else:
        years = docs.years()
        year = int(rok) if rok.isdigit() else (years[0] if years else date.today().year)
        shown = [d for d in rows if year_of(d["id"]) == year]
    shown.sort(key=lambda d: d["id"], reverse=True)
    return render(
        request,
        "doklady/seznam.html",
        rows=shown,
        queue_count=len(queue),
        unpaid_count=len(unpaid),
        filtr=filtr,
        accept=ACCEPT,
        years=docs.years(),
        rok=rok,
    )


@router.post("/nahrat")
async def doc_upload(request: Request) -> Response:
    form = await request.form()
    files = [f for f in form.getlist("soubory") if isinstance(f, UploadFile) and f.filename]
    source = DocSource.PHOTO if form.get("zdroj") == "foto" else DocSource.UPLOAD
    if not files:
        return _list_with_errors(request, ["Vyberte soubor s dokladem."])
    limit = request.app.state.settings.max_upload_bytes
    docs = _docs(request)
    created: list[str] = []
    errors: list[str] = []
    for f in files[:MAX_FILES]:
        data = await f.read(limit + 1)
        name = (f.filename or "soubor")[:80]
        if len(data) > limit:
            errors.append(f"{name}: soubor je větší než {limit // (1024 * 1024)} MB.")
            continue
        try:
            created.append(docs.upload(data, source)["id"])
        except UploadError as exc:
            errors.append(f"{name}: {exc}")
    log.info("Uploaded %d received documents", len(created))
    if errors:
        return _list_with_errors(request, errors, uploaded=len(created))
    if len(created) == 1:
        return RedirectResponse(f"/doklady/{created[0]}", status_code=303)
    return RedirectResponse("/doklady?filtr=kontrola", status_code=303)


def _list_with_errors(request: Request, errors: list[str], uploaded: int = 0) -> Response:
    docs = _docs(request)
    rows = docs.queue()
    return render(
        request,
        "doklady/seznam.html",
        status_code=400,
        rows=rows,
        queue_count=len(rows),
        unpaid_count=len([d for d in docs.all() if d["stav"] == DocState.CONFIRMED]),
        filtr="kontrola",
        accept=ACCEPT,
        years=docs.years(),
        rok="",
        errors=errors,
        info=f"Nahráno dokladů: {uploaded}." if uploaded else None,
    )


# -- form ----------------------------------------------------------------------


def _form_page(request: Request, doc: Record, status_code: int = 200, **ctx: Any) -> Response:
    uncertain = set(filter(None, str(doc.get("nejista_pole") or "").split(",")))
    hints = []
    if doc.get("castka") and doc.get("kategorie"):
        hints = hints_for_expense(int(doc["kategorie"]), doc["castka"])
    docs = _docs(request)
    kind = docs.file_kind(doc) if doc.get("id") and doc.get("soubor") else None
    pages = 0
    if kind is not None and kind.is_pdf:
        path = docs.file_path(doc)
        if path is not None:
            try:
                pdf = pdfium.PdfDocument(str(path))
                pages = min(len(pdf), 5)
                pdf.close()
            except pdfium.PdfiumError:
                pages = 0
    elif kind is not None and kind.is_image:
        pages = 1
    return render(
        request,
        "doklady/detail.html",
        status_code=status_code,
        d=doc,
        uncertain=uncertain,
        hints=hints,
        kind=kind,
        pages=pages,
        categories=EXPENSE_COLUMNS,
        methods=PaymentMethod,
        types=DocType,
        jobs=_jobs(request, str(doc.get("zakazka_id") or "")),
        journal_ready=Journal(request.app.state.storage, docs.firma).ready,
        today=date.today(),
        **ctx,
    )


def _confirmation(form: FormData) -> tuple[Confirmation, list[str], dict[str, Any]]:
    errors: list[str] = []
    raw = {
        k: str(form.get(k, "")).strip()
        for k in (
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
            "datum_uhrady",
            "poznamka",
        )
    }
    issued = parse_date(raw["datum_vystaveni"], "datum vystavení", errors, required=False)
    due = parse_date(raw["datum_splatnosti"], "datum splatnosti", errors, required=False)
    paid = None
    if form.get("uhrazeno"):
        paid = parse_date(raw["datum_uhrady"], "datum úhrady", errors)
    amount = None
    if raw["castka"]:
        try:
            amount = parse_user_amount(raw["castka"])
        except ValueError:
            errors.append("Částka není platné číslo.")
    try:
        column = int(raw["kategorie"])
    except ValueError:
        column = 0
    conf = Confirmation(
        typ=raw["typ"],
        dodavatel_ico=raw["dodavatel_ico"].replace(" ", ""),
        dodavatel_nazev=raw["dodavatel_nazev"],
        cislo_dodavatele=raw["cislo_dodavatele"],
        datum_vystaveni=issued,
        datum_splatnosti=due,
        castka=amount,
        vs=raw["vs"],
        ucet=raw["ucet"],
        popis=raw["popis"],
        kategorie=column,
        zakazka_id=raw["zakazka_id"],
        zpusob_uhrady=raw["zpusob_uhrady"],
        datum_uhrady=paid,
        poznamka=raw["poznamka"],
    )
    # Values to redisplay the form after an error.
    echo: dict[str, Any] = {
        **raw,
        "castka": amount,
        "kategorie": column or None,
        "datum_vystaveni": issued,
        "datum_splatnosti": due,
        "datum_uhrady": paid,
    }
    return conf, errors, echo


@router.get("/novy")
def doc_new(request: Request) -> Response:
    doc: Record = {
        "id": "",
        "typ": "faktura",
        "stav": "",
        "kategorie": 15,
        "zpusob_uhrady": "převod",
        "datum_vystaveni": date.today(),
        "mena": "CZK",
        "soubor": "",
        "nejista_pole": "",
    }
    return _form_page(request, doc, manual=True)


@router.post("/novy")
async def doc_create(request: Request) -> Response:
    conf, errors, echo = _confirmation(await request.form())
    if not errors:
        try:
            rec = _docs(request).confirm(None, conf)
        except ReceivedError as exc:
            errors = str(exc).splitlines()
        else:
            return RedirectResponse(f"/doklady/{rec['id']}?ulozeno=1", status_code=303)
    doc = {"id": "", "stav": "", "soubor": "", "nejista_pole": "", **echo}
    return _form_page(request, doc, status_code=400, errors=errors, manual=True)


@router.get("/ares")
def doc_ares(request: Request, dodavatel_ico: str = "") -> Response:
    """HTMX: supplier fields from ARES."""
    ico = dodavatel_ico.replace(" ", "")
    ctx: dict[str, Any] = {
        "ico": ico,
        "supplier_name": request.query_params.get("dodavatel_nazev", ""),
    }
    if not validate_ico(ico):
        ctx["errors"] = ["IČO nemá platný kontrolní součet."]
    else:
        try:
            subj = request.app.state.ares.lookup(ico)
        except AresUnavailable:
            subj = None
            ctx["errors"] = ["ARES je teď nedostupný."]
        if subj is not None:
            ctx.update(
                ico=normalize_ico(ico), supplier_name=subj.nazev, info="Dodavatel ověřen v ARES."
            )
        elif "errors" not in ctx:
            ctx["errors"] = ["Subjekt s tímto IČO v ARES neexistuje."]
    return render(request, "doklady/_dodavatel.html", uncertain=set(), **ctx)


# -- detail ---------------------------------------------------------------------


def _get(request: Request, doc_id: str) -> Record:
    doc = _docs(request).get(doc_id)
    if doc is None:
        raise HTTPException(404, "Doklad neexistuje.")
    return doc


@router.get("/{doc_id}")
def doc_detail(request: Request, doc_id: str) -> Response:
    return _form_page(request, _get(request, doc_id))


@router.post("/{doc_id}")
async def doc_confirm(request: Request, doc_id: str) -> Response:
    doc = _get(request, doc_id)
    conf, errors, echo = _confirmation(await request.form())
    if not errors:
        try:
            _docs(request).confirm(doc_id, conf)
        except ReceivedError as exc:
            errors = str(exc).splitlines()
        else:
            nxt = _docs(request).queue()
            if doc["stav"] == DocState.REVIEW and nxt:
                return RedirectResponse(
                    f"/doklady/{nxt[0]['id']}?potvrzeno={doc_id}", status_code=303
                )
            return RedirectResponse(f"/doklady/{doc_id}?ulozeno=1", status_code=303)
    return _form_page(request, {**doc, **echo}, status_code=400, errors=errors)


@router.post("/{doc_id}/uhradit")
async def doc_pay(request: Request, doc_id: str) -> Response:
    form = await request.form()
    errors: list[str] = []
    when = parse_date(str(form.get("datum_uhrady", "")), "datum úhrady", errors)
    method = str(form.get("zpusob_uhrady", ""))
    if method not in {m.value for m in PaymentMethod}:
        errors.append("Vyberte způsob úhrady.")
    if when and when > date.today():
        errors.append("Datum úhrady nesmí být v budoucnosti.")
    if not errors and when:
        try:
            _docs(request).pay(doc_id, when, PaymentMethod(method))
        except ReceivedError as exc:
            errors.append(str(exc))
    if errors:
        return _form_page(request, _get(request, doc_id), status_code=400, errors=errors)
    return RedirectResponse(f"/doklady/{doc_id}", status_code=303)


@router.post("/{doc_id}/neuhrazeno")
def doc_unpay(request: Request, doc_id: str) -> Response:
    try:
        _docs(request).unpay(doc_id)
    except ReceivedError as exc:
        return _form_page(request, _get(request, doc_id), status_code=400, errors=[str(exc)])
    return RedirectResponse(f"/doklady/{doc_id}", status_code=303)


@router.post("/{doc_id}/smazat")
def doc_discard(request: Request, doc_id: str) -> Response:
    try:
        _docs(request).discard(doc_id)
    except ReceivedError as exc:
        return _form_page(request, _get(request, doc_id), status_code=400, errors=[str(exc)])
    return RedirectResponse("/doklady?filtr=kontrola", status_code=303)


# -- files ----------------------------------------------------------------------


@router.get("/{doc_id}/soubor")
def doc_file(request: Request, doc_id: str) -> Response:
    docs = _docs(request)
    doc = _get(request, doc_id)
    path, kind = docs.file_path(doc), docs.file_kind(doc)
    if path is None or kind is None:
        raise HTTPException(404, "Doklad nemá soubor.")
    return Response(
        path.read_bytes(),
        media_type=kind.mime,
        headers={"Content-Disposition": f'attachment; filename="{doc_id}.{kind.ext}"'},
    )


@router.get("/{doc_id}/nahled.png")
def doc_preview(request: Request, doc_id: str, strana: int = 1) -> Response:
    """Page preview as PNG (works on iPhone, never runs anything from the document)."""
    docs = _docs(request)
    doc = _get(request, doc_id)
    path, kind = docs.file_path(doc), docs.file_kind(doc)
    if path is None or kind is None or not (kind.is_pdf or kind.is_image):
        raise HTTPException(404, "Náhled není k dispozici.")
    try:
        if kind.is_pdf:
            pdf = pdfium.PdfDocument(str(path))
            try:
                if not 1 <= strana <= len(pdf):
                    raise HTTPException(404, "Strana neexistuje.")
                image = pdf[strana - 1].render(scale=PREVIEW_SCALE).to_pil()
            finally:
                pdf.close()
        else:
            image = Image.open(path)
            image.thumbnail((1400, 1400))
    except (pdfium.PdfiumError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(404, "Náhled se nepodařilo vytvořit.") from exc
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-cache"})
