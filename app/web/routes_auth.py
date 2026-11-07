"""Login and logout."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from starlette.responses import RedirectResponse, Response

from app.auth import new_token
from app.web.security import SESSION_CSRF, SESSION_USER, is_logged_in, verify_csrf
from app.web.templating import render

log = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(verify_csrf)])


def safe_next(target: str | None) -> str:
    """Only allow local absolute paths as redirect targets."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/prihlaseni")
def login_form(request: Request, next: str | None = None) -> Response:
    if not request.app.state.passwords.is_set():
        return RedirectResponse("/pruvodce/heslo", status_code=303)
    if is_logged_in(request):
        return RedirectResponse(safe_next(next), status_code=303)
    return render(request, "prihlaseni.html", next=safe_next(next))


@router.post("/prihlaseni")
def login(
    request: Request,
    heslo: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "/",
) -> Response:
    throttle = request.app.state.throttle
    client = client_key(request)
    if throttle.is_blocked(client):
        log.warning("Login blocked by throttling")
        return render(
            request,
            "prihlaseni.html",
            status_code=429,
            next=safe_next(next),
            error="Příliš mnoho neúspěšných pokusů. Zkuste to znovu za 15 minut.",
        )
    if not request.app.state.passwords.verify(heslo):
        throttle.record_failure(client)
        log.warning("Failed login attempt")
        return render(
            request,
            "prihlaseni.html",
            status_code=401,
            next=safe_next(next),
            error="Nesprávné heslo.",
        )
    throttle.reset(client)
    log_in(request)
    log.info("User logged in")
    return RedirectResponse(safe_next(next), status_code=303)


def log_in(request: Request) -> None:
    # New session on login prevents session fixation.
    request.session.clear()
    request.session[SESSION_USER] = "admin"
    request.session[SESSION_CSRF] = new_token()


@router.post("/odhlaseni")
def logout(request: Request) -> Response:
    request.session.clear()
    return RedirectResponse("/prihlaseni", status_code=303)
