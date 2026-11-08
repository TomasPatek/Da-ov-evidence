"""Issued invoices: list, issue form, detail, PDF/ISDOC/QR, send, pay, cancel."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.datastructures import FormData
from starlette.responses import RedirectResponse, Response

from app.config import FirmaConfig
from app.contacts import KONTAKTY_SCHEMA
from app.invoices.isdoc import build_isdoc
from app.invoices.pdf import render_pdf
from app.invoices.schemas import InvoiceState
from app.invoices.service import (
    OPEN_STATES,
    DraftLine,
    InvoiceDraft,
    InvoiceError,
    InvoiceService,
    InvoiceView,
)
from app.invoices.spayd import qr_svg
from app.invoices.totals import line_total
from app.jobs import ZAKAZKY_SCHEMA
from app.journal import Journal, PaymentMethod
from app.mail.smtp import Attachment, MailError, build_message
from app.money import (
    format_csv_amount,
    format_csv_decimal,
    parse_user_amount,
    parse_user_decimal,
    sum_money,
)
from app.storage import Record
from app.web.forms import EMAIL_RE, parse_date, read_upload
from app.web.routes_contacts import contact_choices
from app.web.security import verify_csrf
from app.web.templating import render

log = logging.getLogger(__name__)
router = APIRouter(prefix="/faktury", dependencies=[Depends(verify_csrf)])

BLANK_LINES = 3


@dataclass
class FormLine:
    popis: str = ""
    mnozstvi: str = "1"
    jednotka: str = "ks"
    cena: str = ""
    celkem: Decimal | None = None


def _service(request: Request) -> InvoiceService:
    firma = FirmaConfig.load(request.app.state.settings.firma_path)
    return InvoiceService(request.app.state.storage, firma)


def _pdf_renderer(request: Request):  # type: ignore[no-untyped-def]
    branding = request.app.state.settings.branding_dir
    return lambda view: render_pdf(view, branding)


def _form_lines(form: FormData) -> list[FormLine]:
    cols = [form.getlist(name) for name in ("popis", "mnozstvi", "jednotka", "cena")]
    lines = []
    for popis, mnozstvi, jednotka, cena in zip(*cols, strict=False):
        line = FormLine(str(popis), str(mnozstvi), str(jednotka), str(cena))
        try:
            line.celkem = line_total(
                parse_user_decimal(line.mnozstvi), parse_user_amount(line.cena)
            )
        except ValueError:
            line.celkem = None
        lines.append(line)
    return lines


def _is_blank(line: FormLine) -> bool:
    return not line.popis.strip() and not line.cena.strip()


def _draft_from_form(form: FormData) -> tuple[InvoiceDraft | None, list[FormLine], list[str]]:
    errors: list[str] = []
    lines = _form_lines(form)
    draft_lines = []
    for i, line in enumerate(lines, start=1):
        if _is_blank(line):
            continue
        try:
            qty = parse_user_decimal(line.mnozstvi)
        except ValueError:
            errors.append(f"Položka {i}: množství není číslo.")
            continue
        try:
            price = parse_user_amount(line.cena)
        except ValueError:
            errors.append(f"Položka {i}: cena není platná částka.")
            continue
        draft_lines.append(DraftLine(line.popis, qty, line.jednotka, price))
    issued = parse_date(str(form.get("datum_vystaveni", "")), "datum vystavení", errors)
    due = parse_date(str(form.get("datum_splatnosti", "")), "datum splatnosti", errors)
    if errors or issued is None or due is None:
        return None, lines, errors
    draft = InvoiceDraft(
        kontakt_id=str(form.get("kontakt_id", "")),
        zakazka_id=str(form.get("zakazka_id", "")),
        datum_vystaveni=issued,
        datum_splatnosti=due,
        lines=draft_lines,
        poznamka=str(form.get("poznamka", "")),
    )
    return draft, lines, errors


def _form_page(request: Request, status_code: int = 200, **ctx: Any) -> Response:
    current = ctx.get("v", {}).get("zakazka_id", "")
    jobs = [
        j
        for j in request.app.state.storage.table(ZAKAZKY_SCHEMA).all()
        if j["stav"] != "uhrazeno" or j["id"] == current
    ]
    jobs.sort(key=lambda j: j["id"], reverse=True)
    return render(
        request,
        "faktury/nova.html",
        status_code=status_code,
        contacts=contact_choices(request),
        jobs=jobs,
        **ctx,
    )


# -- list ------------------------------------------------------------------


@router.get("")
def invoice_list(request: Request, rok: str = "", stav: str = "") -> Response:
    svc = _service(request)
    years = svc.years()
    year = int(rok) if rok.isdigit() else (years[0] if years else date.today().year)
    rows = svc.invoices(year) if year in years else []
    if stav == "neuhrazene":
        rows = [r for r in rows if r["stav"] in OPEN_STATES]
    elif stav:
        rows = [r for r in rows if r["stav"] == stav]
    rows.sort(key=lambda r: r["cislo"], reverse=True)
    contacts = {c["id"]: c for c in request.app.state.storage.table(KONTAKTY_SCHEMA).all()}
    today = date.today()
    active = [r for r in rows if r["stav"] != InvoiceState.CANCELLED]
    return render(
        request,
        "faktury/seznam.html",
        rows=rows,
        contacts=contacts,
        years=years,
        year=year,
        stav=stav,
        today=today,
        total=sum_money(r["castka"] for r in active),
    )


# -- issuing ---------------------------------------------------------------


@router.get("/nova")
def invoice_new(request: Request, kontakt: str = "", zakazka: str = "") -> Response:
    firma = FirmaConfig.load(request.app.state.settings.firma_path)
    job = request.app.state.storage.table(ZAKAZKY_SCHEMA).get(zakazka) if zakazka else None
    if job is not None:
        kontakt = job["kontakt_id"]
    today = date.today()
    values = {
        "kontakt_id": kontakt,
        "zakazka_id": job["id"] if job else "",
        "datum_vystaveni": today.isoformat(),
        "datum_splatnosti": (today + timedelta(days=firma.fakturace.splatnost_dni)).isoformat(),
        "poznamka": "",
    }
    lines = [FormLine(popis=job["nazev"] if job else "")] + [
        FormLine() for _ in range(BLANK_LINES - 1)
    ]
    return _form_page(request, v=values, lines=lines, total=None)


@router.get("/radek")
def invoice_line_row(request: Request) -> Response:
    """HTMX: one more empty line."""
    return render(request, "faktury/_radek.html", line=FormLine())


@router.post("/soucet")
async def invoice_total_preview(request: Request) -> Response:
    """HTMX: recomputed line totals and invoice total while typing."""
    lines = _form_lines(await request.form())
    totals = [line.celkem for line in lines if line.celkem is not None and not _is_blank(line)]
    return render(request, "faktury/_soucet.html", total=sum_money(totals) if totals else None)


@router.post("/nova")
async def invoice_issue(request: Request) -> Response:
    form = await request.form()
    draft, lines, errors = _draft_from_form(form)
    values = {
        k: str(form.get(k, ""))
        for k in ("kontakt_id", "zakazka_id", "datum_vystaveni", "datum_splatnosti", "poznamka")
    }
    if draft is not None:
        try:
            record = _service(request).issue(draft, render_pdf=_pdf_renderer(request))
        except InvoiceError as exc:
            errors = str(exc).splitlines()
        else:
            log.info("Invoice issued")
            return RedirectResponse(f"/faktury/{record['cislo']}?nova=1", status_code=303)
    while len(lines) < BLANK_LINES:
        lines.append(FormLine())
    totals = [line.celkem for line in lines if line.celkem is not None and not _is_blank(line)]
    return _form_page(
        request,
        status_code=400,
        v=values,
        lines=lines,
        errors=errors,
        total=sum_money(totals) if totals else None,
    )


# -- detail and files -------------------------------------------------------


def _view(request: Request, cislo: str) -> InvoiceView:
    view = _service(request).view(cislo)
    if view is None:
        raise HTTPException(404, "Faktura neexistuje.")
    return view


def _detail(request: Request, cislo: str, status_code: int = 200, **ctx: Any) -> Response:
    view = _view(request, cislo)
    mailer = request.app.state.mailer
    return render(
        request,
        "faktury/detail.html",
        status_code=status_code,
        view=view,
        inv=view.invoice,
        open_states=OPEN_STATES,
        today=date.today(),
        mail_ready=mailer.configured,
        methods=PaymentMethod,
        journal_rows=Journal(request.app.state.storage, view.firma).for_document(cislo),
        **ctx,
    )


@router.get("/{cislo}")
def invoice_detail(request: Request, cislo: str) -> Response:
    return _detail(request, cislo)


def _pdf_bytes(request: Request, cislo: str) -> bytes:
    svc = _service(request)
    view = _view(request, cislo)
    path = svc.pdf_path(view.invoice)
    if not path.exists():
        # Regenerate a missing file (e.g. restored data without attachments).
        svc.write_pdf(view.invoice, _pdf_renderer(request))
    return path.read_bytes()


@router.get("/{cislo}/pdf")
def invoice_pdf(request: Request, cislo: str) -> Response:
    data = _pdf_bytes(request, cislo)
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="faktura-{cislo}.pdf"'},
    )


@router.get("/{cislo}/isdoc")
def invoice_isdoc(request: Request, cislo: str) -> Response:
    return Response(
        build_isdoc(_view(request, cislo)),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="faktura-{cislo}.isdoc"'},
    )


@router.get("/{cislo}/qr.svg")
def invoice_qr(request: Request, cislo: str) -> Response:
    view = _view(request, cislo)
    if not view.spayd:
        raise HTTPException(404, "Faktura nemá QR platbu.")
    return Response(qr_svg(view.spayd), media_type="image/svg+xml")


# -- editing ------------------------------------------------------------------


def _editable(request: Request, cislo: str) -> Record:
    invoice = _view(request, cislo).invoice
    if invoice["stav"] not in OPEN_STATES:
        raise HTTPException(400, "Upravit lze jen neuhrazenou a nestornovanou fakturu.")
    if invoice.get("zdroj"):
        raise HTTPException(400, f"Faktura vznikla v {invoice['zdroj']}; opravte ji tam.")
    return invoice


@router.get("/{cislo}/upravit")
def invoice_edit_form(request: Request, cislo: str, potvrzeno: str = "") -> Response:
    invoice = _editable(request, cislo)
    if invoice["datum_odeslani"] and not potvrzeno:
        return render(request, "faktury/upravit-odeslanou.html", inv=invoice)
    draft = _service(request).draft_of(cislo)
    values = {
        "kontakt_id": draft.kontakt_id,
        "zakazka_id": draft.zakazka_id,
        "datum_vystaveni": draft.datum_vystaveni.isoformat(),
        "datum_splatnosti": draft.datum_splatnosti.isoformat(),
        "poznamka": draft.poznamka,
    }
    lines = [
        FormLine(
            line.popis,
            format_csv_decimal(line.mnozstvi),
            line.jednotka,
            format_csv_amount(line.cena_jednotkova),
            line.celkem,
        )
        for line in draft.lines
    ]
    lines.append(FormLine())
    return _form_page(
        request,
        v=values,
        lines=lines,
        total=draft.total,
        edit_cislo=cislo,
        sent_on=invoice["datum_odeslani"],
    )


@router.post("/{cislo}/upravit")
async def invoice_edit(request: Request, cislo: str) -> Response:
    invoice = _editable(request, cislo)
    form = await request.form()
    if invoice["datum_odeslani"] and not form.get("potvrzeno"):
        return render(request, "faktury/upravit-odeslanou.html", status_code=400, inv=invoice)
    draft, lines, errors = _draft_from_form(form)
    if draft is not None:
        try:
            _service(request).update(cislo, draft, render_pdf=_pdf_renderer(request))
        except InvoiceError as exc:
            errors = str(exc).splitlines()
        else:
            log.info("Invoice updated")
            return RedirectResponse(f"/faktury/{cislo}?upraveno=1", status_code=303)
    values = {
        k: str(form.get(k, ""))
        for k in ("kontakt_id", "zakazka_id", "datum_vystaveni", "datum_splatnosti", "poznamka")
    }
    totals = [line.celkem for line in lines if line.celkem is not None and not _is_blank(line)]
    return _form_page(
        request,
        status_code=400,
        v=values,
        lines=lines,
        errors=errors,
        total=sum_money(totals) if totals else None,
        edit_cislo=cislo,
        sent_on=invoice["datum_odeslani"],
    )


# -- state changes ----------------------------------------------------------


@router.post("/{cislo}/uhrazena")
async def invoice_paid(request: Request, cislo: str) -> Response:
    form = await request.form()
    errors: list[str] = []
    when = parse_date(str(form.get("datum_uhrady", "")), "datum úhrady", errors)
    method_text = str(form.get("zpusob_uhrady", PaymentMethod.TRANSFER.value))
    method = (
        PaymentMethod(method_text)
        if method_text in {m.value for m in PaymentMethod}
        else PaymentMethod.TRANSFER
    )
    photo = await read_upload(form, "priloha", request.app.state.settings.max_upload_bytes, errors)
    if when is not None and not errors:
        try:
            _service(request).mark_paid(
                cislo,
                when,
                method=method,
                kod_transakce=str(form.get("kod_transakce", "")),
                attachment=photo,
            )
        except InvoiceError as exc:
            errors.append(str(exc))
    if errors:
        return _detail(request, cislo, status_code=400, errors=errors)
    return RedirectResponse(f"/faktury/{cislo}", status_code=303)


@router.post("/{cislo}/neuhrazena")
def invoice_unpaid(request: Request, cislo: str) -> Response:
    try:
        _service(request).mark_unpaid(cislo)
    except InvoiceError as exc:
        return _detail(request, cislo, status_code=400, errors=[str(exc)])
    return RedirectResponse(f"/faktury/{cislo}", status_code=303)


@router.post("/{cislo}/storno")
async def invoice_cancel(request: Request, cislo: str) -> Response:
    form = await request.form()
    try:
        _service(request).cancel(cislo, str(form.get("duvod", "")))
    except InvoiceError as exc:
        return _detail(request, cislo, status_code=400, errors=[str(exc)])
    log.info("Invoice cancelled")
    return RedirectResponse(f"/faktury/{cislo}", status_code=303)


# -- e-mail -------------------------------------------------------------------


def _default_mail(view: InvoiceView) -> dict[str, str]:
    inv, f = view.invoice, view.firma.firma
    amount = f"{inv['castka']:.2f}".replace(".", ",")
    due = inv["datum_splatnosti"]
    body = (
        "Dobrý den,\n\n"
        f"v příloze posílám fakturu č. {inv['cislo']} na částku {amount} Kč "
        f"se splatností {due.day}. {due.month}. {due.year}.\n"
        f"Variabilní symbol: {inv['vs']}. Na faktuře je QR kód pro rychlou platbu.\n\n"
        f"S pozdravem\n{f.nazev}\n{f.telefon}".rstrip()
        + "\n"
    )
    return {
        "komu": view.customer.get("email", ""),
        "predmet": f"Faktura {inv['cislo']} – {f.nazev}",
        "text": body,
        "isdoc": "",
    }


@router.get("/{cislo}/odeslat")
def invoice_send_form(request: Request, cislo: str) -> Response:
    view = _view(request, cislo)
    return render(
        request,
        "faktury/odeslat.html",
        view=view,
        inv=view.invoice,
        m=_default_mail(view),
        mail_ready=request.app.state.mailer.configured,
        sender=request.app.state.mailer.sender_address,
    )


@router.post("/{cislo}/odeslat")
async def invoice_send(request: Request, cislo: str) -> Response:
    view = _view(request, cislo)
    mailer = request.app.state.mailer
    form = await request.form()
    m = {k: str(form.get(k, "")).strip() for k in ("komu", "predmet", "text", "isdoc")}
    errors = []
    if view.invoice["stav"] == InvoiceState.CANCELLED:
        errors.append("Stornovanou fakturu nelze odeslat.")
    if not EMAIL_RE.match(m["komu"]):
        errors.append("Zadejte platnou e-mailovou adresu příjemce.")
    if not m["predmet"]:
        errors.append("Vyplňte předmět.")
    if not errors:
        attachments = [
            Attachment(f"faktura-{cislo}.pdf", _pdf_bytes(request, cislo), "application", "pdf")
        ]
        if m["isdoc"]:
            attachments.append(
                Attachment(f"faktura-{cislo}.isdoc", build_isdoc(view), "application", "xml")
            )
        message = build_message(
            view.firma.firma.nazev,
            mailer.sender_address,
            m["komu"],
            m["predmet"],
            m["text"],
            attachments,
        )
        try:
            mailer.send(message)
        except MailError as exc:
            errors.append(str(exc))
        else:
            _service(request).mark_sent(cislo, date.today())
            return RedirectResponse(f"/faktury/{cislo}?odeslano=1", status_code=303)
    return render(
        request,
        "faktury/odeslat.html",
        status_code=400,
        view=view,
        inv=view.invoice,
        m=m,
        errors=errors,
        mail_ready=mailer.configured,
        sender=mailer.sender_address,
    )
