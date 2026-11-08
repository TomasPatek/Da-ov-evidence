"""Periodic mail fetching inside the app (APScheduler, one job, never overlapping)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from app.backup import Backup
from app.backup import configured as backup_configured
from app.config import FirmaConfig, Settings
from app.mail.fetch import FetchResult, MailProcessor
from app.mail.imap import Mailbox, imap_configured
from app.storage import Storage

log = logging.getLogger(__name__)

MailboxFactory = Callable[[], Mailbox]


def fetch_now(settings: Settings, storage: Storage, factory: MailboxFactory) -> FetchResult:
    firma = FirmaConfig.load(settings.firma_path)
    return MailProcessor(storage, firma, settings).run(factory())


def backup_now(settings: Settings) -> None:
    Backup(settings).backup()


def start_scheduler(
    settings: Settings, storage: Storage, factory: MailboxFactory
) -> BackgroundScheduler | None:
    """Mail every N minutes and the nightly backup; nothing runs when neither is set up."""
    mail = settings.posta_interval_min > 0 and imap_configured(settings)
    backup = backup_configured(settings)
    if not mail and not backup:
        log.info("Automatic mail fetching and backup are off")
        return None
    scheduler = BackgroundScheduler(timezone="Europe/Prague")
    if mail:
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
        log.info("Mail fetching every %d minutes", settings.posta_interval_min)
    if backup:
        hour, _, minute = settings.backup_time.partition(":")
        scheduler.add_job(
            backup_now,
            "cron",
            hour=int(hour or 2),
            minute=int(minute or 30),
            args=(settings,),
            id="zaloha",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=6 * 3600,
        )
        log.info("Nightly backup at %s", settings.backup_time)
    scheduler.start()
    return scheduler
