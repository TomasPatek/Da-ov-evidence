"""Login gate, CSRF protection and security headers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from urllib.parse import quote

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, Response

from app.auth import new_token, tokens_equal

SESSION_USER = "user"
SESSION_CSRF = "csrf"
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "x-csrf-token"

PUBLIC_PATHS = frozenset({"/prihlaseni", "/zdravi", "/favicon.ico"})
PUBLIC_PREFIXES = ("/static/", "/branding/")
SETUP_PATH = "/pruvodce/heslo"

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


def csrf_token(request: Request) -> str:
    token = request.session.get(SESSION_CSRF)
    if not token:
        token = new_token()
        request.session[SESSION_CSRF] = token
    return str(token)


def is_logged_in(request: Request) -> bool:
    return bool(request.session.get(SESSION_USER))


async def verify_csrf(request: Request) -> None:
    """FastAPI dependency: reject state-changing requests without a valid token."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    sent = request.headers.get(CSRF_HEADER)
    if not sent:
        form = await request.form()
        value = form.get(CSRF_FIELD)
        sent = value if isinstance(value, str) else None
    if not tokens_equal(sent, request.session.get(SESSION_CSRF)):
        raise HTTPException(status_code=403, detail="Neplatný bezpečnostní token formuláře.")


def _redirect(request: Request, url: str) -> Response:
    if request.headers.get("hx-request"):
        # HTMX would swap the login page into a fragment; ask for a full navigation.
        return Response(status_code=401, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


class AuthGateMiddleware(BaseHTTPMiddleware):
    """Every page requires login, except the login page, health check and assets.

    Before a password exists, only the first wizard step is reachable.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)
        if not request.app.state.passwords.is_set():
            if path == SETUP_PATH:
                return await call_next(request)
            return _redirect(request, SETUP_PATH)
        if not is_logged_in(request):
            target = path + (f"?{request.url.query}" if request.url.query else "")
            return _redirect(request, f"/prihlaseni?next={quote(target)}")
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        h = response.headers
        h.setdefault("Content-Security-Policy", CSP)
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy", "geolocation=(), microphone=()")
        if not request.url.path.startswith("/static/"):
            h.setdefault("Cache-Control", "no-store")
        return response
