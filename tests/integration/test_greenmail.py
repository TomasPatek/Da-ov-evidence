"""Real IMAP against GreenMail (docker-compose.test.yml). Runs when GREENMAIL_HOST is set."""

from __future__ import annotations

import os
import smtplib
from pathlib import Path

import pytest
from imap_tools import MailBoxUnencrypted

from app.banks.book import BankBook
from app.config import FirmaConfig, Settings
from app.mail.fetch import MailProcessor
from app.mail.imap import ImapMailbox
from app.storage import Storage
from tests.unit.test_mail_fetch import doc_mail, other_mail

HOST = os.environ.get("GREENMAIL_HOST", "")
pytestmark = pytest.mark.skipif(not HOST, reason="GREENMAIL_HOST not set (GreenMail not running)")
AIRBANK = Path(__file__).parents[1] / "fixtures" / "airbank"
USER = "fakturace@example.cz"


def deliver(data: bytes) -> None:
    with smtplib.SMTP(HOST, int(os.environ.get("GREENMAIL_SMTP_PORT", "3025"))) as smtp:
        smtp.sendmail("info@airbank.cz", [USER], data)


def test_fetch_classifies_and_moves(tmp_path: Path) -> None:
    for data in (
        (AIRBANK / "prichozi-uhrada.eml").read_bytes(),
        doc_mail(),
        other_mail("Greenmail"),
    ):
        deliver(data)
    settings = Settings(
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        secret_key="k",
        imap_host=HOST,
        imap_port=int(os.environ.get("GREENMAIL_IMAP_PORT", "3143")),
        imap_security="none",
        imap_user=USER,
        imap_password=USER,
    )
    firma = FirmaConfig()
    firma.banka.ucet = "1000000005/3030"
    storage = Storage(settings.data_dir)
    processor = MailProcessor(storage, firma, settings)

    result = processor.run(ImapMailbox(settings))
    assert (result.notifications, result.documents, result.other) == (1, 1, 1), result.errors
    assert len(BankBook(storage, firma).all()) == 1

    with MailBoxUnencrypted(HOST, settings.imap_port).login(USER, USER) as box:
        assert len(list(box.fetch(mark_seen=False))) == 1  # only the other mail stays
        box.folder.set("Zpracováno")
        assert len(list(box.fetch(mark_seen=False))) == 2

    # A second run does not process anything again.
    again = processor.run(ImapMailbox(settings))
    assert (again.notifications, again.documents, again.other) == (0, 0, 0)
