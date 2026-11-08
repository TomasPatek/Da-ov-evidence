"""IMAP access behind a small interface so tests can use an in-memory mailbox."""

from __future__ import annotations

import contextlib
import ssl
from collections.abc import Iterator
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol

from imap_tools import BaseMailBox, MailBox, MailBoxStartTls, MailBoxUnencrypted

from app.config import Settings


@dataclass(frozen=True)
class RawMessage:
    uid: str
    data: bytes


class Mailbox(Protocol):
    def messages(self) -> Iterator[RawMessage]: ...

    def move(self, uid: str, folder: str) -> None: ...

    def __enter__(self) -> Mailbox: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...


class MailError(Exception):
    """Mailbox not configured or unreachable (message safe to show, no secrets)."""


def imap_configured(settings: Settings) -> bool:
    return bool(settings.imap_host and settings.imap_user and settings.imap_password)


class ImapMailbox:
    """INBOX of the configured account; messages are read without marking them as seen."""

    def __init__(self, settings: Settings, timeout: float = 30) -> None:
        self._s = settings
        self._timeout = timeout
        self._box: BaseMailBox | None = None

    def __enter__(self) -> ImapMailbox:
        s = self._s
        if not imap_configured(s):
            raise MailError("Stahování pošty není nastavené (IMAP v souboru .env).")
        try:
            box: BaseMailBox
            if s.imap_security == "none":
                box = MailBoxUnencrypted(s.imap_host, s.imap_port, timeout=self._timeout)
            elif s.imap_security == "starttls":
                box = MailBoxStartTls(
                    s.imap_host,
                    s.imap_port,
                    timeout=self._timeout,
                    ssl_context=ssl.create_default_context(),
                )
            else:
                box = MailBox(
                    s.imap_host,
                    s.imap_port,
                    timeout=self._timeout,
                    ssl_context=ssl.create_default_context(),
                )
            box.login(s.imap_user, s.imap_password, initial_folder="INBOX")
        except Exception as exc:
            raise MailError(f"Připojení ke schránce selhalo ({type(exc).__name__}).") from exc
        self._box = box
        if not box.folder.exists(s.imap_done_folder):
            box.folder.create(s.imap_done_folder)
        box.folder.set("INBOX")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._box is not None:
            with contextlib.suppress(Exception):  # closing a broken connection
                self._box.logout()
            self._box = None

    def messages(self) -> Iterator[RawMessage]:
        assert self._box is not None  # noqa: S101 - only used inside "with"
        for msg in self._box.fetch("ALL", mark_seen=False, bulk=20):
            if msg.uid:
                yield RawMessage(uid=msg.uid, data=msg.obj.as_bytes())

    def move(self, uid: str, folder: str) -> None:
        assert self._box is not None  # noqa: S101
        self._box.move(uid, folder)
