"""Application factory. Run with ``uvicorn app.main:create_app --factory``."""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from app import __version__
from app.ares.client import AresClient, HttpAresClient
from app.auth import LoginThrottle, PasswordStore
from app.config import Settings
from app.mail.imap import ImapMailbox
from app.mail.scheduler import MailboxFactory, start_scheduler
from app.mail.smtp import MailSender, SmtpSender
from app.storage import LockedYearError, Storage
from app.web import (
    routes_auth,
    routes_bank,
    routes_contacts,
    routes_invoices,
    routes_jobs,
    routes_journal,
    routes_main,
    routes_received,
    routes_reports,
    routes_wizard,
)
from app.web.security import AuthGateMiddleware, SecurityHeadersMiddleware
from app.web.templating import render

log = logging.getLogger("app")

STATIC_DIR = Path(__file__).parent / "web" / "static"


def create_app(
    settings: Settings | None = None,
    ares: AresClient | None = None,
    mailer: MailSender | None = None,
    mailbox_factory: MailboxFactory | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        scheduler = start_scheduler(
            app.state.settings, app.state.storage, app.state.mailbox_factory
        )
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)

    app = FastAPI(
        lifespan=lifespan,
        title="Daňová evidence",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.storage = Storage(settings.data_dir)
    app.state.passwords = PasswordStore(settings.auth_path)
    app.state.throttle = LoginThrottle()
    app.state.ares = ares or HttpAresClient()
    app.state.mailer = mailer or SmtpSender(settings)
    app.state.mailbox_factory = mailbox_factory or (lambda: ImapMailbox(settings))
    app.state.setup_token = settings.setup_token or secrets.token_hex(4).upper()

    settings.config_dir.mkdir(parents=True, exist_ok=True)
    settings.branding_dir.mkdir(parents=True, exist_ok=True)
    app.state.storage.ensure_layout()

    if not app.state.passwords.is_set():
        # Printed at WARNING so it is visible in `docker compose logs` by default.
        log.warning("První spuštění: kód pro nastavení hesla je %s", app.state.setup_token)

    # Middleware order: the last added runs first. Session must wrap the auth gate.
    app.add_middleware(AuthGateMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="de_session",
        max_age=settings.session_max_age,
        same_site="strict",
        https_only=settings.cookie_secure,
    )
    app.add_middleware(SecurityHeadersMiddleware)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(routes_auth.router)
    app.include_router(routes_wizard.router)
    app.include_router(routes_contacts.router)
    app.include_router(routes_jobs.router)
    app.include_router(routes_invoices.router)
    app.include_router(routes_received.router)
    app.include_router(routes_journal.router)
    app.include_router(routes_bank.router)
    app.include_router(routes_reports.router)
    app.include_router(routes_main.router)

    @app.exception_handler(LockedYearError)
    async def locked_year(request: Request, exc: LockedYearError) -> Response:
        return render(request, "chyba.html", status_code=409, message=str(exc), code=409)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> Response:
        return render(
            request,
            "chyba.html",
            status_code=exc.status_code,
            message=str(exc.detail),
            code=exc.status_code,
        )

    return app
