"""Jinja2 environment shared by all routes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from app import __version__
from app.banks.ucet import format_iban
from app.config import FirmaConfig
from app.money import format_display_amount
from app.web.branding import logo_path
from app.web.security import CSRF_FIELD, csrf_token, is_logged_in

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["app_version"] = __version__
templates.env.globals["csrf_field"] = CSRF_FIELD


def _czk(value: Decimal, currency: str = "Kč") -> str:
    return format_display_amount(value, currency)


def _cz_date(value: date | None) -> str:
    return f"{value.day}. {value.month}. {value.year}" if value else ""


templates.env.filters["czk"] = _czk
templates.env.filters["cz_date"] = _cz_date
templates.env.filters["iban"] = format_iban


def render(request: Request, name: str, status_code: int = 200, **context: Any) -> Response:
    settings = request.app.state.settings
    firma = FirmaConfig.load(settings.firma_path)
    base = {
        "csrf_token": csrf_token(request),
        "logged_in": is_logged_in(request),
        "firma": firma,
        "has_logo": logo_path(settings.branding_dir) is not None,
    }
    return templates.TemplateResponse(request, name, {**base, **context}, status_code=status_code)
