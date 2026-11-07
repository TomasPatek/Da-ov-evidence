"""Sending invoices by e-mail over SMTP (behind an interface for tests)."""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Protocol

from app.config import Settings

log = logging.getLogger(__name__)


class MailError(Exception):
    """Sending failed. The message is safe to show (contains no secrets)."""


class MailSender(Protocol):
    def send(self, message: EmailMessage) -> None: ...

    @property
    def configured(self) -> bool: ...

    @property
    def sender_address(self) -> str: ...


@dataclass
class Attachment:
    filename: str
    data: bytes
    maintype: str
    subtype: str


def build_message(
    sender_name: str,
    sender_address: str,
    to: str,
    subject: str,
    body: str,
    attachments: list[Attachment],
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((sender_name, sender_address))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=sender_address.rpartition("@")[2] or None)
    msg.set_content(body)
    for a in attachments:
        msg.add_attachment(a.data, maintype=a.maintype, subtype=a.subtype, filename=a.filename)
    return msg


class SmtpSender:
    def __init__(self, settings: Settings, timeout: float = 30) -> None:
        self._s = settings
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._s.smtp_host and self.sender_address)

    @property
    def sender_address(self) -> str:
        return self._s.smtp_from or self._s.smtp_user

    def send(self, message: EmailMessage) -> None:
        s = self._s
        if not self.configured:
            raise MailError("Odesílání e-mailů není nastavené (SMTP v souboru .env).")
        context = ssl.create_default_context()
        try:
            smtp: smtplib.SMTP
            if s.smtp_security == "ssl":
                smtp = smtplib.SMTP_SSL(
                    s.smtp_host, s.smtp_port, timeout=self._timeout, context=context
                )
            else:
                smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=self._timeout)
            with smtp:
                if s.smtp_security == "starttls":
                    smtp.starttls(context=context)
                if s.smtp_user and s.smtp_password:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(message)
        except smtplib.SMTPAuthenticationError as exc:
            raise MailError(
                "Server odmítl přihlášení. Zkontrolujte SMTP_USER a SMTP_PASSWORD."
            ) from exc
        except (smtplib.SMTPException, OSError) as exc:
            # Only the exception type is logged: messages may echo addresses.
            log.warning("SMTP send failed: %s", type(exc).__name__)
            raise MailError(
                f"Odeslání se nepovedlo ({type(exc).__name__}). Zkuste to znovu."
            ) from exc
        log.info("Invoice e-mail sent")
