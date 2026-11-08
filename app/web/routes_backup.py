"""Backup status page and manual start."""

from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, Request
from starlette.responses import RedirectResponse, Response

from app.backup import Backup, configured
from app.web.security import verify_csrf
from app.web.templating import render

router = APIRouter(prefix="/zaloha", dependencies=[Depends(verify_csrf)])
_running = threading.Lock()


@router.get("")
def backup_page(request: Request) -> Response:
    settings = request.app.state.settings
    backup = Backup(settings)
    return render(
        request,
        "zaloha.html",
        configured=configured(settings),
        s=settings,
        last=backup.state().get("posledni"),
        snapshots=backup.snapshots() if request.query_params.get("seznam") else None,
        running=_running.locked(),
    )


@router.post("/spustit")
def backup_start(request: Request) -> Response:
    settings = request.app.state.settings
    if configured(settings) and _running.acquire(blocking=False):

        def job() -> None:
            try:
                Backup(settings).backup()
            finally:
                _running.release()

        threading.Thread(target=job, name="zaloha", daemon=True).start()
    return RedirectResponse("/zaloha?bezi=1", status_code=303)
