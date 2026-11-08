"""Assets with depreciation, annual overview with exports, year lock."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.responses import RedirectResponse, Response
from weasyprint import HTML
from weasyprint.urls import URLFetcher

from app.assets import AssetBook, AssetDraft, AssetError, asset_schedule
from app.config import FirmaConfig
from app.money import format_display_amount, parse_user_amount
from app.tax.annual import annual_report, to_markdown
from app.tax.depreciation import GROUPS, DepreciationError, Method
from app.web.forms import parse_date
from app.web.security import verify_csrf
from app.web.templating import render

router = APIRouter(dependencies=[Depends(verify_csrf)])
TEMPLATE_DIR = Path(__file__).parent / "templates"


def _assets(request: Request) -> AssetBook:
    return AssetBook(request.app.state.storage)


# -- assets ---------------------------------------------------------------------------


@router.get("/majetek")
def asset_list(request: Request, rok: str = "") -> Response:
    year = int(rok) if rok.isdigit() else date.today().year
    book = _assets(request)
    rows = []
    for a in book.all():
        try:
            sched = asset_schedule(a)
        except DepreciationError:
            sched = []
        this = next((r for r in sched if r.rok == year), None)
        rows.append(
            {
                "a": a,
                "odpis": this.odpis if this else Decimal("0"),
                "zc": this.zustatkova_cena if this else None,
            }
        )
    return render(
        request, "majetek/seznam.html", rows=rows, year=year, total=book.total_depreciation(year)
    )


def _asset_form(request: Request, status_code: int = 200, **ctx: Any) -> Response:
    return render(
        request,
        "majetek/formular.html",
        status_code=status_code,
        groups=GROUPS,
        methods=Method,
        **ctx,
    )


def _draft(form: dict[str, str]) -> tuple[AssetDraft | None, list[str]]:
    errors: list[str] = []
    when = parse_date(form.get("datum_porizeni", ""), "datum pořízení", errors)
    try:
        price = parse_user_amount(form.get("vstupni_cena", ""))
    except ValueError:
        errors.append("Vstupní cena není platná částka.")
        price = None
    try:
        group = int(form.get("odpisova_skupina", ""))
    except ValueError:
        group = 0
    if errors or when is None or price is None:
        return None, errors
    return AssetDraft(
        form.get("nazev", ""),
        when,
        price,
        group,
        form.get("zpusob_odpisu", ""),
        form.get("doklad_id", ""),
        form.get("poznamka", ""),
    ), errors


async def _form(request: Request) -> dict[str, str]:
    data = await request.form()
    return {k: str(v).strip() for k, v in data.items() if isinstance(v, str)}


@router.get("/majetek/novy")
def asset_new(request: Request, doklad: str = "", nazev: str = "", cena: str = "") -> Response:
    v = {
        "nazev": nazev,
        "datum_porizeni": date.today().isoformat(),
        "vstupni_cena": cena,
        "odpisova_skupina": "2",
        "zpusob_odpisu": "rovnoměrný",
        "doklad_id": doklad,
        "poznamka": "",
    }
    return _asset_form(request, v=v)


@router.post("/majetek/novy")
async def asset_create(request: Request) -> Response:
    form = await _form(request)
    draft, errors = _draft(form)
    if draft is not None:
        try:
            rec = _assets(request).add(draft)
        except AssetError as exc:
            errors = str(exc).splitlines()
        else:
            return RedirectResponse(f"/majetek/{rec['id']}", status_code=303)
    return _asset_form(request, status_code=400, v=form, errors=errors)


def _detail(request: Request, asset_id: str, status_code: int = 200, **ctx: Any) -> Response:
    try:
        a = _assets(request).get(asset_id)
    except AssetError as exc:
        raise HTTPException(404, str(exc)) from exc
    try:
        sched = asset_schedule(a)
    except DepreciationError as exc:
        sched, ctx["errors"] = [], [str(exc)]
    v = {k: (a[k].isoformat() if hasattr(a[k], "isoformat") else a[k]) for k in a}
    v["vstupni_cena"] = f"{a['vstupni_cena']:.2f}".replace(".", ",")
    return render(
        request,
        "majetek/detail.html",
        status_code=status_code,
        a=a,
        v=v,
        schedule=sched,
        groups=GROUPS,
        methods=Method,
        **ctx,
    )


@router.get("/majetek/{asset_id}")
def asset_detail(request: Request, asset_id: str) -> Response:
    return _detail(request, asset_id)


@router.post("/majetek/{asset_id}")
async def asset_save(request: Request, asset_id: str) -> Response:
    form = await _form(request)
    draft, errors = _draft(form)
    if draft is not None:
        try:
            _assets(request).update(asset_id, draft)
        except AssetError as exc:
            errors = str(exc).splitlines()
        else:
            return RedirectResponse(f"/majetek/{asset_id}?ulozeno=1", status_code=303)
    return _detail(request, asset_id, status_code=400, errors=errors)


@router.post("/majetek/{asset_id}/vyradit")
async def asset_dispose(request: Request, asset_id: str) -> Response:
    form = await _form(request)
    errors: list[str] = []
    when = parse_date(form.get("datum_vyrazeni", ""), "datum vyřazení", errors, required=False)
    if not errors:
        try:
            _assets(request).dispose(asset_id, when)
        except AssetError as exc:
            errors.append(str(exc))
    if errors:
        return _detail(request, asset_id, status_code=400, errors=errors)
    return RedirectResponse(f"/majetek/{asset_id}", status_code=303)


@router.post("/majetek/{asset_id}/prerusit/{year}")
def asset_interrupt(request: Request, asset_id: str, year: int) -> Response:
    _assets(request).toggle_interruption(asset_id, year)
    return RedirectResponse(f"/majetek/{asset_id}", status_code=303)


# -- annual overview ----------------------------------------------------------------------


def _year(rok: str) -> int:
    return int(rok) if rok.isdigit() else date.today().year


@router.get("/prehledy")
def report_page(request: Request, rok: str = "") -> Response:
    year = _year(rok)
    firma = FirmaConfig.load(request.app.state.settings.firma_path)
    report = annual_report(request.app.state.storage, firma, year)
    return render(
        request,
        "prehledy/rocni.html",
        r=report,
        year=year,
        locked=request.app.state.storage.is_locked(year),
    )


@router.get("/prehledy/{year}.md")
def report_markdown(request: Request, year: int) -> Response:
    firma = FirmaConfig.load(request.app.state.settings.firma_path)
    text = to_markdown(annual_report(request.app.state.storage, firma, year), firma)
    return Response(
        text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="prehled-{year}.md"'},
    )


@router.get("/prehledy/{year}.pdf")
def report_pdf(request: Request, year: int) -> Response:
    firma = FirmaConfig.load(request.app.state.settings.firma_path)
    report = annual_report(request.app.state.storage, firma, year)
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"]))
    env.filters["czk"] = lambda v: format_display_amount(v)
    html = env.get_template("prehledy/pdf.html").render(r=report, firma=firma)
    pdf = HTML(
        string=html, url_fetcher=URLFetcher(allowed_protocols={"data"}, timeout=1)
    ).write_pdf()
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="prehled-{year}.pdf"'},
    )


# -- year lock ------------------------------------------------------------------------------


@router.post("/nastaveni/zamek")
async def year_lock(request: Request) -> Response:
    form = await _form(request)
    storage = request.app.state.storage
    try:
        year = int(form.get("rok", ""))
    except ValueError:
        return RedirectResponse("/nastaveni", status_code=303)
    if form.get("akce") == "odemknout":
        if form.get("potvrzeni") != str(year):
            return RedirectResponse(f"/nastaveni?zamek_chyba={year}#zamek", status_code=303)
        storage.set_locked(year, False)
    else:
        storage.set_locked(year, True)
    return RedirectResponse("/nastaveni?ulozeno=1#zamek", status_code=303)
