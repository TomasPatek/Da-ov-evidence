"""Processing the mailbox: bank notifications, documents in attachments, the rest.

* Bank notification -> bank movement, automatic matching -> moved to "Zpracováno".
* Message with a PDF, photo or ISDOC attachment -> received documents "ke kontrole"
  -> moved to "Zpracováno".
* Anything else stays in the inbox for the user and is remembered, so it is not read
  again on the next run.
"""

from __future__ import annotations

import email
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from email import policy
from email.message import EmailMessage
from typing import Any

from app.banks import parser_for_email
from app.banks.book import BankBook, BankError, MatchState
from app.config import FirmaConfig, Settings
from app.ingest.files import UploadError, detect
from app.mail.imap import Mailbox, MailError
from app.received import DocSource, ReceivedDocs
from app.storage import Storage
from app.storage.atomic import atomic_write_text, file_lock

log = logging.getLogger(__name__)

STATE_FILE = "posta.json"
MAX_SEEN = 5000


@dataclass
class FetchResult:
    started: str = ""
    notifications: int = 0
    matched: int = 0
    documents: int = 0
    other: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cas": self.started,
            "notifikace": self.notifications,
            "sparovano": self.matched,
            "doklady": self.documents,
            "ostatni": self.other,
            "chyby": self.errors,
        }


class MailProcessor:
    def __init__(self, storage: Storage, firma: FirmaConfig, settings: Settings) -> None:
        self.storage = storage
        self.firma = firma
        self.settings = settings
        self.state_path = storage.data_dir / STATE_FILE

    # -- state ---------------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self, seen: list[str], result: FetchResult) -> None:
        data = {"videne": seen[-MAX_SEEN:], "posledni_beh": result.as_dict()}
        atomic_write_text(self.state_path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")

    # -- run -----------------------------------------------------------------------

    def run(self, mailbox: Mailbox) -> FetchResult:
        result = FetchResult(started=datetime.now().astimezone().isoformat(timespec="seconds"))
        self.storage.data_dir.mkdir(parents=True, exist_ok=True)
        with file_lock(self.storage.data_dir / "posta"):
            seen = list(self.state().get("videne", []))
            seen_set = set(seen)
            try:
                with mailbox as box:
                    for raw in box.messages():
                        msg = email.message_from_bytes(raw.data, policy=policy.default)
                        assert isinstance(msg, EmailMessage)  # noqa: S101
                        key = self._key(msg, raw.data)
                        if key in seen_set:
                            continue
                        try:
                            handled = self._process(msg, result)
                        except Exception as exc:
                            log.warning("Mail processing failed: %s", type(exc).__name__)
                            result.errors.append(f"Zpráva {raw.uid}: {type(exc).__name__}")
                            handled = False
                        if handled:
                            box.move(raw.uid, self.settings.imap_done_folder)
                        else:
                            result.other += 1
                        seen.append(key)
                        seen_set.add(key)
            except MailError as exc:
                result.errors.append(str(exc))
            self._save_state(seen, result)
        log.info(
            "Mail fetch: %d notifications (%d matched), %d documents, %d other, %d errors",
            result.notifications,
            result.matched,
            result.documents,
            result.other,
            len(result.errors),
        )
        return result

    @staticmethod
    def _key(msg: EmailMessage, data: bytes) -> str:
        message_id = str(msg.get("Message-ID", "")).strip()
        return message_id or "sha256:" + hashlib.sha256(data).hexdigest()

    def _process(self, msg: EmailMessage, result: FetchResult) -> bool:
        parser = parser_for_email(msg)
        if parser is not None:
            movement = parser.parse_email(msg)
            if movement is None:
                return False
            book = BankBook(self.storage, self.firma)
            try:
                record, _ = book.import_movement(movement)
            except BankError as exc:
                result.errors.append(str(exc))
                return False
            result.notifications += 1
            if book.auto_match(record)["stav"] == MatchState.MATCHED:
                result.matched += 1
            return True
        docs = ReceivedDocs(self.storage, self.firma)
        created = 0
        for part in msg.iter_attachments():
            data = part.get_payload(decode=True)
            if not isinstance(data, bytes) or len(data) > self.settings.max_upload_bytes:
                continue
            try:
                detect(data)
            except UploadError:
                continue
            docs.upload(data, DocSource.EMAIL)
            created += 1
        result.documents += created
        return created > 0
