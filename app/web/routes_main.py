"""Dashboard, settings, branding assets and health check."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Request
from starlette.responses import FileResponse, RedirectResponse, Response

from app.config import FirmaConfig
from app.invoices.schemas import InvoiceState
from app.invoices.service import OPEN_STATES, InvoiceService
from app.jobs import ZAKAZKY_SCHEMA, JobState
from app.money import sum_money
from app.storage import Record
from app.web.branding import logo_path, theme_path
from app.web.routes_jobs import job_warnings
from app.web.security import verify_csrf
from app.web.templating import render

router = APIRouter(dependencies=[Depends(verify_csrf)])


@router.get("/zdravi")
def health() -> dict[str, str]:
    return {"stav": "ok"}


@router.get("/")
def dashboard(request: Request) -> Response:
    firma = FirmaConfig.load(request.app.state.settings.firma_path)
    if not firma.aplikace.pruvodce_dokoncen:
        return RedirectResponse("/pruvodce", status_code=303)
    return render(request, "prehled.html", **_overview(request, firma))


def _overview(request: Request, firma: FirmaConfig) -> dict[str, Any]:
    svc = InvoiceService(request.app.state.storage, firma)
    today = date.today()
    invoices = svc.all_invoices()
    unpaid = [i for i in invoices if i["stav"] in OPEN_STATES]
    overdue = [i for i in unpaid if i["datum_splatnosti"] < today]
    this_year = [
        i
        for i in invoices
        if i["datum_vystaveni"].year == today.year and i["stav"] != InvoiceState.CANCELLED
    ]
    jobs = request.app.state.storage.table(ZAKAZKY_SCHEMA).all()
    running = [j for j in jobs if j["stav"] in (JobState.INQUIRY, JobState.IN_PROGRESS)]
    warn_jobs = [j for j in jobs if job_warnings(j, svc_job(invoices, j["id"]))]
    return {
        "unpaid_sum": sum_money(i["castka"] for i in unpaid),
        "unpaid_count": len(unpaid),
        "overdue": sorted(overdue, key=lambda i: i["datum_splatnosti"]),
        "invoiced_year": sum_money(i["castka"] for i in this_year),
        "paid_year": sum_money(i["castka"] for i in this_year if i["stav"] == InvoiceState.PAID),
        "year": today.year,
        "running_jobs": len(running),
        "warn_jobs": warn_jobs,
    }


def svc_job(invoices: list[Record], job_id: str) -> list[Record]:
    return [i for i in invoices if i["zakazka_id"] == job_id]


@router.get("/nastaveni")
def settings_page(request: Request) -> Response:
    return render(request, "nastaveni.html")


@router.get("/branding/theme.css")
def theme_css(request: Request) -> Response:
    path = theme_path(request.app.state.settings.branding_dir)
    return FileResponse(path, media_type="text/css", headers={"Cache-Control": "no-cache"})


@router.get("/branding/logo")
def logo(request: Request) -> Response:
    path = logo_path(request.app.state.settings.branding_dir)
    if path is None:
        return Response(status_code=404)
    media = "image/svg+xml" if path.suffix == ".svg" else "image/png"
    return FileResponse(
        path,
        media_type=media,
        headers={
            "Cache-Control": "no-cache",
            # SVG opened directly must not run anything.
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        },
    )
