"""Periodic mail fetching inside the app (APScheduler, one job, never overlapping)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import FirmaConfig, Settings
from app.mail.fetch import FetchResult, MailProcessor
from app.mail.imap import Mailbox, imap_configured
from app.storage import Storage

log = logging.getLogger(__name__)

MailboxFactory = Callable[[], Mailbox]


def fetch_now(settings: Settings, storage: Storage, factory: MailboxFactory) -> FetchResult:
    firma = FirmaConfig.load(settings.firma_path)
    return MailProcessor(storage, firma, settings).run(factory())


def start_scheduler(
    settings: Settings, storage: Storage, factory: MailboxFactory
) -> BackgroundScheduler | None:
    if settings.posta_interval_min <= 0 or not imap_configured(settings):
        log.info("Automatic mail fetching is off")
        return None
    scheduler = BackgroundScheduler(timezone="Europe/Prague")
    scheduler.add_job(
        fetch_now,
        "interval",
        minutes=settings.posta_interval_min,
        args=(settings, storage, factory),
        id="posta",
        max_instances=1,
        coalesce=True,
        # First run shortly after start, then every interval.
        next_run_time=datetime.now(ZoneInfo("Europe/Prague")) + timedelta(seconds=30),
    )
    scheduler.start()
    log.info("Mail fetching every %d minutes", settings.posta_interval_min)
    return scheduler
