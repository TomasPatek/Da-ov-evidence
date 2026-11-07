"""Dashboard, settings, branding assets and health check."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from starlette.responses import FileResponse, RedirectResponse, Response

from app.config import FirmaConfig
from app.web.branding import logo_path, theme_path
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
    return render(request, "prehled.html")


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
