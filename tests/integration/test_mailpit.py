"""Real SMTP delivery to Mailpit (docker-compose.test.yml). Runs when MAILPIT_URL is set."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.mail.smtp import Attachment, SmtpSender, build_message

MAILPIT_URL = os.environ.get("MAILPIT_URL", "")
pytestmark = pytest.mark.skipif(not MAILPIT_URL, reason="MAILPIT_URL not set (Mailpit not running)")


def test_invoice_mail_arrives_with_pdf(tmp_path: Path) -> None:
    httpx.delete(f"{MAILPIT_URL}/api/v1/messages")
    settings = Settings(
        data_dir=tmp_path,
        config_dir=tmp_path,
        secret_key="k",
        smtp_host=os.environ.get("MAILPIT_SMTP_HOST", "127.0.0.1"),
        smtp_port=int(os.environ.get("MAILPIT_SMTP_PORT", "1025")),
        smtp_security="none",
        smtp_from="fakturace@example.cz",
    )
    msg = build_message(
        "Jana Vzorová",
        "fakturace@example.cz",
        "petr@example.cz",
        "Faktura 20260001",
        "Dobrý den, posílám fakturu.",
        [Attachment("faktura-20260001.pdf", b"%PDF-1.7 test", "application", "pdf")],
    )
    SmtpSender(settings).send(msg)

    listing = httpx.get(f"{MAILPIT_URL}/api/v1/messages").json()
    assert listing["total"] == 1
    summary = listing["messages"][0]
    assert summary["Subject"] == "Faktura 20260001"
    assert summary["To"][0]["Address"] == "petr@example.cz"
    detail = httpx.get(f"{MAILPIT_URL}/api/v1/message/{summary['ID']}").json()
    (att,) = detail["Attachments"]
    assert att["FileName"] == "faktura-20260001.pdf"
    assert att["ContentType"] == "application/pdf"
